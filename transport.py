"""Bounded authenticated loopback JSON. Private inputs and credentials are not logged."""
from __future__ import annotations

import hmac
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, ProxyHandler

from contracts import DomainError, canonical, parse_json, require

MAX_BODY = 8 * 1024 * 1024


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = False
    request_queue_size = 16

    def __init__(self, app, token: str, port: int = 0, origins: tuple[str, ...] = ()):
        require(len(token) >= 32, "session_token_too_short")
        self.app, self.token, self.origins = app, token, origins
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(("127.0.0.1", port), Handler)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def do_GET(self):
        self.dispatch()

    def do_POST(self):
        self.dispatch()

    def do_OPTIONS(self):
        self.send_error(405)

    def dispatch(self):
        try:
            require(self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}",
                    "invalid_host", 403)
            origin = self.headers.get("Origin")
            require(origin is None or origin in self.server.origins, "invalid_origin", 403)
            auth = self.headers.get("Authorization", "")
            require(hmac.compare_digest(auth.encode(), ("Bearer " + self.server.token).encode()),
                    "unauthorized", 401)
            require(not self.headers.get("Transfer-Encoding"), "unsupported_transfer_encoding")
            payload = None
            if self.command == "POST":
                require(self.headers.get_content_type() == "application/json", "json_required", 415)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise DomainError("invalid_content_length") from None
                require(0 < length <= MAX_BODY, "body_size_exceeded", 413)
                raw = self.rfile.read(length)
                require(len(raw) == length, "incomplete_body")
                payload = parse_json(raw)
                require(isinstance(payload, dict), "object_required")
            result = self.server.app.handle(self.command, self.path, payload)
            self.respond(200, result)
        except DomainError as error:
            self.respond(error.status, {"error": error.code})
        except (ConnectionError, TimeoutError, OSError):
            self.respond(503, {"error": "service_unavailable"})
        except Exception:
            self.respond(500, {"error": "internal_error"})

    def respond(self, status: int, payload: object):
        body = canonical(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (ConnectionError, OSError):
            pass
        self.close_connection = True


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class Client:
    def __init__(self, url: str, token: str, timeout: float = 3):
        parsed = urlsplit(url)
        require(parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
                and parsed.port is not None and not parsed.username
                and not parsed.password and parsed.path in ("", "/")
                and not parsed.query and not parsed.fragment, "loopback_url_required")
        self.url, self.token, self.timeout = url.rstrip("/"), token, timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def call(self, method: str, path: str, payload: dict | None = None):
        require(path.startswith("/v1/") and not path.startswith("//") and "://" not in path,
                "invalid_api_path")
        body = None if payload is None else canonical(payload).encode("utf-8")
        request = Request(self.url + path, data=body, method=method,
                          headers={"Authorization": "Bearer " + self.token,
                                   "Content-Type": "application/json"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(MAX_BODY + 1)
                require(len(raw) <= MAX_BODY, "response_size_exceeded", 502)
                return parse_json(raw)
        except HTTPError as error:
            try:
                value = parse_json(error.read(MAX_BODY))
                code = value.get("error", "upstream_error") if isinstance(value, dict) else "upstream_error"
            except DomainError:
                code = "upstream_error"
            raise DomainError(code, error.code) from None
        except (URLError, TimeoutError, ValueError):
            raise DomainError("service_unavailable", 503) from None
