"""Local UI gateway. Business data stays behind authenticated service APIs."""
from __future__ import annotations

import argparse
import mimetypes
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlsplit

from contracts import DomainError, canonical, parse_json, require
from transport import Client, Handler, LocalServer

ROOT = Path(__file__).resolve().parent


class Gateway:
    def __init__(self, urls: dict, token: str, front_dir: Path = ROOT / "frontend/dist"):
        require(isinstance(urls, dict) and {"profile", "knowledge", "evaluation"}.issubset(urls),
                "required_services_missing")
        self.clients = {name: Client(url, token) for name, url in urls.items()}
        self.front_dir = front_dir.resolve()
        require((self.front_dir / "index.html").is_file(), "frontend_build_missing", 503)

    def handle(self, method, path, body):
        if method == "GET" and path == "/api/demo":
            return parse_json((ROOT / "fixtures/demo.json").read_bytes())
        if method == "GET" and path == "/api/status":
            def check(entry):
                name, client = entry
                try:
                    value = Client(client.url, client.token, timeout=.5).call("GET", "/v1/health")
                    return name, {"state": "ready", **value}
                except DomainError:
                    return name, {"state": "unavailable"}
            with ThreadPoolExecutor(max_workers=len(self.clients)) as pool:
                statuses = dict(pool.map(check, self.clients.items()))
            return {"services": statuses, "degraded": any(s["state"] != "ready" for s in statuses.values())}
        parts = path.split("/")
        if len(parts) >= 4 and parts[:2] == ["", "api"] and parts[2] in self.clients:
            return self.clients[parts[2]].call(method, "/v1/" + "/".join(parts[3:]), body)
        raise DomainError("not_found", 404)


class GatewayHandler(Handler):
    def do_GET(self):
        if self.path.startswith("/api/"):
            self.dispatch()
            return
        try:
            require(self.headers.get("Host") == f"127.0.0.1:{self.server.server_port}", "invalid_host", 403)
            origin = self.headers.get("Origin")
            require(origin is None or origin in self.server.origins, "invalid_origin", 403)
            parsed = urlsplit(self.path)
            require(not parsed.scheme and not parsed.netloc, "invalid_path", 403)
            name = unquote(parsed.path).lstrip("/") or "index.html"
            path = (self.server.app.front_dir / name).resolve()
            require(path.is_relative_to(self.server.app.front_dir) and path.is_file(), "not_found", 404)
            require(path.suffix in (".html", ".js", ".css", ".svg", ".png", ".ico"), "not_found", 404)
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "img-src 'self' data:; connect-src 'self' ipc: http://ipc.localhost; "
                             "font-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)
        except DomainError as error:
            self.respond(error.status, {"error": error.code})
        except (ConnectionError, OSError):
            self.close_connection = True


def create_gateway(urls, token, front_dir=ROOT / "frontend/dist", port=0):
    server = LocalServer(Gateway(urls, token, front_dir), token, port)
    server.RequestHandlerClass = GatewayHandler
    server.origins = (server.url,)
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--front-dir", type=Path, default=ROOT / "frontend/dist")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--parent-stdio", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("LOOTWEAVE_SESSION_TOKEN", "")
    urls = parse_json(os.environ.get("LOOTWEAVE_SERVICE_URLS", "{}"))
    server = create_gateway(urls, token, args.front_dir, args.port)
    if args.parent_stdio:
        def watch_parent():
            sys.stdin.buffer.read()
            server.shutdown()
        threading.Thread(target=watch_parent, daemon=True).start()
    print(canonical({"service": "gateway", "url": server.url, "contract_version": 1}), flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
