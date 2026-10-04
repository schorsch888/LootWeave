"""Developer launcher and packaged service entry point. Rust owns desktop supervision."""
from __future__ import annotations

import argparse
import os
import queue
import secrets
import signal
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

from contracts import DomainError, canonical, parse_json, require
from gateway import create_gateway
from transport import Client
from storage import acquire_instance_lock

ROOT = Path(__file__).resolve().parent
SERVICES = ("profile", "knowledge", "evaluation", "planning", "ocr")


class Runtime:
    def __init__(self, data_dir: Path, token: str | None = None, front_dir=ROOT / "frontend/dist"):
        self.data_dir = data_dir.resolve()
        self.token = token or secrets.token_urlsafe(32)
        self.front_dir = front_dir
        self.children = []
        self.urls = {}
        self.lock = None
        self.gateway = None

    def acquire_lock(self):
        self.lock = acquire_instance_lock(self.data_dir)

    def start(self):
        self.acquire_lock()
        try:
            for name in SERVICES:
                self.start_service(name)
            self.gateway = create_gateway(self.urls, self.token, self.front_dir)
            threading.Thread(target=self.gateway.serve_forever, kwargs={"poll_interval": .1}, daemon=True).start()
            return self
        except BaseException:
            self.stop()
            raise

    def start_service(self, name):
        command = [sys.executable, "--service", name] if getattr(sys, "frozen", False) else \
                  [sys.executable, "-u", str(ROOT / "service.py"), name]
        command += ["--data-dir", str(self.data_dir), "--parent-stdio"]
        if name in ("evaluation", "planning"):
            command += ["--knowledge-url", self.urls["knowledge"]]
        if name == "evaluation":
            command += ["--profile-url", self.urls["profile"]]
        environment = {**os.environ, "LOOTWEAVE_SESSION_TOKEN": self.token, "PYTHONUTF8": "1"}
        environment.pop("LOOTWEAVE_PARENT_JOB", None)  # This launcher creates independent service roots.
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        self.children.append(process)
        ready = queue.Queue(maxsize=1)
        def read_ready():
            ready.put(process.stdout.readline(4096))
        threading.Thread(target=read_ready, daemon=True).start()
        try:
            line = ready.get(timeout=8)
        except queue.Empty:
            raise DomainError("service_start_timeout", 503) from None
        require(bool(line), "service_start_failed:" + name, 503)
        value = parse_json(line)
        require(value.get("service") == name and value.get("contract_version") == 1, "incompatible_service", 503)
        url = value.get("url")
        Client(url, self.token).call("GET", "/v1/health")
        self.urls[name] = url

    def stop(self):
        if self.gateway:
            self.gateway.shutdown()
            self.gateway.server_close()
            self.gateway = None
        for process in self.children:
            if process.stdin:
                process.stdin.close()
        deadline = time.monotonic() + 4
        for process in self.children:
            try:
                process.wait(timeout=max(.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                process.terminate()
        for process in self.children:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            if process.stdout:
                process.stdout.close()
        self.children.clear()
        if self.lock:
            self.lock.close()
            self.lock = None


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--maintenance":
        sys.argv.pop(1)
        from maintenance import main as maintenance_main
        return maintenance_main()
    if len(sys.argv) > 1 and sys.argv[1] in ("--service", "--gateway"):
        mode = sys.argv.pop(1)
        if mode == "--service":
            from service import main as service_main
            return service_main()
        from gateway import main as gateway_main
        return gateway_main()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".local")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--stdio-control", action="store_true")
    args = parser.parse_args()
    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    runtime = Runtime(args.data_dir)
    try:
        runtime.start()
        # IPC readiness carries the credential only to an owning parent, never to normal logs.
        if args.stdio_control:
            print(canonical({"url": runtime.gateway.url, "token": runtime.token,
                             "pids": [p.pid for p in runtime.children]}), flush=True)
            def watch_parent():
                sys.stdin.buffer.read()
                stopped.set()
            threading.Thread(target=watch_parent, daemon=True).start()
        else:
            print("Local UI ready at " + runtime.gateway.url, flush=True)
        if not args.no_browser:
            webbrowser.open(runtime.gateway.url + "/#session=" + runtime.token)
        stopped.wait()
    except (DomainError, OSError) as error:
        print(canonical({"error": error.code if isinstance(error, DomainError) else "startup_failed"}),
              file=sys.stderr, flush=True)
        return 1
    finally:
        runtime.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
