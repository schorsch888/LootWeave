"""Local UI gateway. Business data stays behind authenticated service APIs."""
from __future__ import annotations

import argparse
import mimetypes
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlsplit

from contracts import DomainError, canonical, parse_json, require
from transport import Client, Handler, LocalServer
from runtime_control import CORE_SERVICES, SERVICES, StdioOwner

ROOT = Path(__file__).resolve().parent


class Gateway:
    def __init__(self, urls: dict, token: str, front_dir: Path = ROOT / "frontend/dist", owner=None):
        require(isinstance(urls, dict) and (owner is not None or set(CORE_SERVICES).issubset(urls)),
                "required_services_missing")
        self.clients = {name: Client(url, token) for name, url in urls.items()}
        self.owner, self.token = owner, token
        self.lock = threading.Lock()
        self.front_dir = front_dir.resolve()
        require((self.front_dir / "index.html").is_file(), "frontend_build_missing", 503)

    def status(self):
        owned = self.owner.status() if self.owner else {"services": {
            name: {"state": "ready", "url": client.url} for name, client in self.clients.items()}}
        require(isinstance(owned.get("services"), dict), "invalid_owner_control", 503)
        states = {name: dict(value) for name, value in owned["services"].items()
                  if name in (*SERVICES, "gateway") and isinstance(value, dict)}

        def check(entry):
            name, value = entry
            # Inactive services are observations, never startup triggers.
            if name == "gateway" or value.get("state") != "ready":
                return name, {key: val for key, val in value.items() if key != "url"}
            try:
                client = Client(value.get("url", ""), self.token, timeout=.5)
                health = client.call("GET", "/v1/health")
                return name, {key: val for key, val in value.items() if key != "url"} | health
            except DomainError:
                return name, {key: val for key, val in value.items() if key != "url"} | {"state": "unavailable"}

        with ThreadPoolExecutor(max_workers=max(1, len(states))) as pool:
            statuses = dict(pool.map(check, states.items()))
        core_ready = all(statuses.get(name, {}).get("state") == "ready" for name in CORE_SERVICES)
        degraded = any(value.get("state") in ("failed", "unavailable") for value in statuses.values())
        result = {"services": statuses, "core_ready": core_ready, "degraded": degraded}
        for key in ("startup_policy", "timings"):
            if key in owned:
                result[key] = owned[key]
        return result

    def ensure_service(self, name):
        require(name in SERVICES, "unsupported_service")
        if self.owner:
            ready = self.owner.ensure_service(name)
            require(ready.get("service") == name and ready.get("state") == "ready",
                    "invalid_owner_control", 503)
            client = Client(ready.get("url", ""), self.token)
            with self.lock:
                self.clients[name] = client
            return {key: value for key, value in ready.items() if key in ("service", "state", "generation")}
        require(name in self.clients, "service_unavailable", 503)
        self.clients[name].call("GET", "/v1/health")
        return {"service": name, "state": "ready", "generation": 0}

    def service_client(self, name, historical=False):
        if self.owner:
            state = self.owner.status().get("services", {}).get(name, {})
            history_ready = historical and state.get("state") == "failed" and state.get("historical_only") is True
            require(state.get("state") == "ready" or history_ready, "service_start_required" if state.get("state")
                    in ("dormant", "starting") else "service_unavailable", 503)
            return Client(state.get("url", ""), self.token)
        require(name in self.clients, "not_found", 404)
        return self.clients[name]

    def handle(self, method, path, body):
        if method == "GET" and path == "/api/demo":
            return parse_json((ROOT / "fixtures/demo.json").read_bytes())
        if method == "GET" and path == "/api/status":
            return self.status()
        if method == "POST" and path == "/api/runtime/ensure":
            require(isinstance(body, dict) and set(body) == {"service"}
                    and isinstance(body["service"], str), "invalid_service_request")
            return self.ensure_service(body["service"])
        parts = path.split("/")
        if len(parts) >= 4 and parts[:2] == ["", "api"] and parts[2] in SERVICES:
            history_id = len(parts) > 4 and parts[4] not in (".", "..") and re.fullmatch(
                r"[a-zA-Z0-9_.-]{1,100}", parts[4]) is not None
            historical = parts[2] == "evaluation" and parts[3] == "evaluations" and (
                (method == "GET" and (len(parts) == 4 or len(parts) == 5 and history_id))
                or (method == "POST" and len(parts) == 6 and history_id and parts[5] == "replay"))
            return self.service_client(parts[2], historical).call(method, "/v1/" + "/".join(parts[3:]), body)
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


def create_gateway(urls, token, front_dir=ROOT / "frontend/dist", port=0, owner=None):
    server = LocalServer(Gateway(urls, token, front_dir, owner), token, port)
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
    owner = StdioOwner(sys.stdin.buffer, sys.stdout.buffer) if os.environ.get("LOOTWEAVE_OWNER_STDIO") == "1" else None
    require(owner is None or args.parent_stdio, "owner_pipe_required", 503)
    server = create_gateway(urls, token, args.front_dir, args.port, owner=owner)
    if owner:
        owner.listen(server.shutdown)
    elif args.parent_stdio:
        def watch_parent():
            sys.stdin.buffer.read()
            server.shutdown()
        threading.Thread(target=watch_parent, daemon=True).start()
    ready = {"service": "gateway", "url": server.url, "contract_version": 1}
    if owner:
        ready["control_version"] = 1
    print(canonical(ready), flush=True)
    try:
        server.serve_forever(poll_interval=.1)
    finally:
        if owner:
            owner.close()
        server.server_close()


if __name__ == "__main__":
    main()
