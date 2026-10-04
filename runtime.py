"""Developer launcher and packaged service entry point. Rust owns desktop supervision."""
from __future__ import annotations

import argparse
import http.client
import io
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
from urllib.parse import urlsplit

from contracts import DomainError, canonical, parse_json, require
from gateway import create_gateway
from transport import Client, MAX_BODY
from storage import acquire_instance_lock
from runtime_control import CORE_SERVICES, SERVICES, START_TIMEOUT

ROOT = Path(__file__).resolve().parent


def verify_service_health(url, token, deadline):
    """Apply the owner's absolute deadline to every HTTP header/body socket read."""
    client = Client(url, token)  # Reuse the business client's strict loopback URL validation.
    parsed = urlsplit(client.url)

    def remaining():
        budget = deadline - time.monotonic()
        require(budget > 0, "service_start_timeout", 503)
        return budget

    class DeadlineReader(io.RawIOBase):
        def __init__(self, connection):
            super().__init__()
            self.connection = connection
            self.stream = connection.makefile("rb", buffering=0)

        def readable(self):
            return True

        def readinto(self, buffer):
            self.connection.settimeout(remaining())
            return self.stream.readinto(buffer)

        def close(self):
            try:
                self.stream.close()
            finally:
                super().close()

    class ResponseSocket:
        def __init__(self, connection):
            self.connection = connection

        def makefile(self, _mode):
            return io.BufferedReader(DeadlineReader(self.connection))

    channel = http.client.HTTPConnection(parsed.hostname, parsed.port, timeout=remaining())
    channel.response_class = lambda connection, **kwargs: http.client.HTTPResponse(ResponseSocket(connection), **kwargs)
    try:
        channel.connect()
        channel.sock.settimeout(remaining())
        channel.request("GET", "/v1/health", headers={"Authorization": "Bearer " + token,
                                                     "Connection": "close"})
        with channel.getresponse() as response:
            require(response.status == 200, "service_unavailable", 503)
            raw = response.read(MAX_BODY + 1)
            require(len(raw) <= MAX_BODY, "response_size_exceeded", 502)
            remaining()
            return parse_json(raw)
    except TimeoutError:
        raise DomainError("service_start_timeout", 503) from None
    except (OSError, http.client.HTTPException, ValueError):
        raise DomainError("service_start_timeout" if time.monotonic() >= deadline
                          else "service_unavailable", 503) from None
    finally:
        channel.close()


class Runtime:
    def __init__(self, data_dir: Path, token: str | None = None, front_dir=ROOT / "frontend/dist",
                 startup_policy="eager"):
        require(startup_policy in ("eager", "on-demand"), "invalid_startup_policy")
        self.data_dir = data_dir.resolve()
        self.token = token or secrets.token_urlsafe(32)
        self.front_dir = front_dir
        self.startup_policy = startup_policy
        self.children = []
        self.urls = {}
        self.lock = None
        self.gateway = None
        self.condition = threading.Condition(threading.RLock())
        self.records = {name: {"state": "dormant", "generation": 0} for name in SERVICES}
        self.stopping = False
        self.core_thread = None
        self.started = time.monotonic()
        self.timings = {"service_spawn_ms": {}, "service_ready_ms": {}, "service_init_ms": {}}

    def acquire_lock(self):
        self.lock = acquire_instance_lock(self.data_dir)

    def start(self):
        self.acquire_lock()
        self.started = time.monotonic()
        try:
            if self.startup_policy == "eager":
                for name in SERVICES:
                    self.start_service(name)
            self.gateway = create_gateway(self.urls, self.token, self.front_dir, owner=self)
            threading.Thread(target=self.gateway.serve_forever, kwargs={"poll_interval": .1}, daemon=True).start()
            with self.condition:
                elapsed = (time.monotonic() - self.started) * 1000
                self.timings.update(shell_ready_ms=elapsed, gateway_ready_ms=elapsed)
                if all(self.records[name]["state"] == "ready" for name in CORE_SERVICES):
                    self.timings["core_ready_ms"] = elapsed
            if self.startup_policy == "on-demand":
                self.core_thread = threading.Thread(target=self.start_core, name="core-startup", daemon=True)
                self.core_thread.start()
            return self
        except BaseException:
            self.stop()
            raise

    def start_core(self):
        def start(name):
            try:
                self.ensure_service(name, retry_failed=False)
            except (DomainError, OSError):
                pass
        threads = [threading.Thread(target=start, args=(name,), daemon=True) for name in CORE_SERVICES[:2]]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        with self.condition:
            ready = all(self.records[name]["state"] == "ready" for name in CORE_SERVICES[:2])
            if not ready and not self.stopping and self.records["evaluation"]["state"] == "dormant":
                self.records["evaluation"].update(state="failed", error="service_dependency_unavailable")
                self.condition.notify_all()
        if ready:
            start("evaluation")

    def refresh(self):
        for name, record in self.records.items():
            child = record.get("process")
            if (record["state"] == "ready" or record.get("historical_only")) and child is not None and child.poll() is not None:
                record["state"] = "failed"
                record["error"] = "service_unavailable"
                record.pop("historical_only", None)
                self.urls.pop(name, None)

        for name, record in self.records.items():
            if record["state"] == "ready" and not self.dependencies_ready(record.get("dependencies", {})):
                record.update(state="failed", error="service_dependency_unavailable")
                if name == "evaluation":
                    # Frozen storage reads do not query Profile or Knowledge.
                    record["historical_only"] = True
                else:
                    self.urls.pop(name, None)

    def dependencies_ready(self, dependencies):
        return all(self.records[name]["state"] == "ready" and self.records[name]["generation"] == generation
                   for name, generation in dependencies.items())

    def status(self):
        with self.condition:
            self.refresh()
            services = {}
            for name, record in self.records.items():
                value = {key: record[key] for key in ("state", "generation", "error", "historical_only") if key in record}
                if record["state"] == "ready" or record.get("historical_only"):
                    value.update(url=self.urls[name], pid=record["process"].pid)
                services[name] = value
            services["gateway"] = {"state": "stopping" if self.stopping else "ready", "pid": os.getpid(),
                                   "generation": 1}
            return {"services": services, "core_ready": all(self.records[name]["state"] == "ready"
                    for name in CORE_SERVICES), "startup_policy": self.startup_policy,
                    "timings": parse_json(canonical(self.timings))}

    def start_service(self, name):
        return self.ensure_service(name)

    def ensure_service(self, name, deadline=None, retry_failed=True):
        require(name in SERVICES, "unsupported_service")
        deadline = deadline if deadline is not None else time.monotonic() + START_TIMEOUT
        attempt_start = time.monotonic()
        joined_record = None
        previous_process = None
        with self.condition:
            while True:
                require(not self.stopping, "service_owner_stopping", 503)
                self.refresh()
                record = self.records[name]
                if joined_record is not None and joined_record["state"] == "failed":
                    raise DomainError(joined_record.get("error", "service_start_failed"), 503)
                if record["state"] == "ready":
                    return {"service": name, "state": "ready", "generation": record["generation"],
                            "url": self.urls[name]}
                if record["state"] != "starting":
                    require(retry_failed or record["state"] != "failed",
                            "service_dependency_unavailable", 503)
                    generation = record["generation"] + 1
                    previous_process = record.get("process")
                    self.records[name] = {"state": "starting", "generation": generation}
                    self.condition.notify_all()
                    break
                joined_record = record
                remaining = deadline - time.monotonic()
                require(remaining > 0, "service_start_timeout", 503)
                self.condition.wait(remaining)
        process = None
        try:
            if previous_process is not None:
                self.stop_child(previous_process, timeout=.5)
                with self.condition:
                    if previous_process in self.children:
                        self.children.remove(previous_process)
            dependencies = {}
            if name in ("evaluation", "planning"):
                dependencies["knowledge"] = self.ensure_service("knowledge", deadline, retry_failed)["generation"]
            if name == "evaluation":
                dependencies["profile"] = self.ensure_service("profile", deadline, retry_failed)["generation"]
            command = self.service_command(name)
            environment = {**os.environ, "LOOTWEAVE_SESSION_TOKEN": self.token, "PYTHONUTF8": "1"}
            environment.pop("LOOTWEAVE_PARENT_JOB", None)
            with self.condition:
                require(not self.stopping and time.monotonic() < deadline, "service_owner_stopping"
                        if self.stopping else "service_start_timeout", 503)
                self.refresh()
                require(self.dependencies_ready(dependencies), "service_dependency_unavailable", 503)
                spawn_started = time.monotonic()
                process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                           stderr=subprocess.DEVNULL, env=environment,
                                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.children.append(process)
                self.records[name]["process"] = process
                self.records[name]["dependencies"] = dependencies
                self.timings["service_spawn_ms"][name] = (time.monotonic() - spawn_started) * 1000
            ready = queue.Queue(maxsize=1)
            def read_ready():
                try:
                    ready.put(process.stdout.readline(4097))
                except (OSError, ValueError):
                    ready.put(b"")
            threading.Thread(target=read_ready, daemon=True).start()
            try:
                line = ready.get(timeout=max(.001, deadline - time.monotonic()))
            except queue.Empty:
                raise DomainError("service_start_timeout", 503) from None
            require(bool(line) and len(line) <= 4096 and line.endswith(b"\n"), "service_start_failed", 503)
            value = parse_json(line)
            require(value.get("service") == name and value.get("contract_version") == 1,
                    "incompatible_service", 503)
            url = value.get("url")
            remaining = deadline - time.monotonic()
            require(remaining > 0, "service_start_timeout", 503)
            verify_service_health(url, self.token, deadline)
            with self.condition:
                self.refresh()
                require(time.monotonic() < deadline, "service_start_timeout", 503)
                require(self.dependencies_ready(dependencies), "service_dependency_unavailable", 503)
                require(not self.stopping and self.records[name]["generation"] == generation
                        and self.records[name]["state"] == "starting", "service_owner_stopping", 503)
                self.urls[name] = url
                self.records[name]["state"] = "ready"
                self.timings["service_ready_ms"][name] = (time.monotonic() - attempt_start) * 1000
                if isinstance(value.get("startup_timings"), dict):
                    self.timings["service_init_ms"][name] = value["startup_timings"]
                if self.gateway is not None and all(self.records[key]["state"] == "ready" for key in CORE_SERVICES):
                    self.timings.setdefault("core_ready_ms", (time.monotonic() - self.started) * 1000)
                self.condition.notify_all()
                return {"service": name, "state": "ready", "generation": generation, "url": url}
        except BaseException as error:
            if process:
                self.stop_child(process, timeout=.5)
            with self.condition:
                if process in self.children:
                    self.children.remove(process)
                if self.records[name]["generation"] == generation and not self.stopping:
                    self.records[name].update(state="failed", error=error.code if isinstance(error, DomainError)
                                              else "service_start_failed")
                    self.records[name].pop("process", None)
                    self.urls.pop(name, None)
                self.condition.notify_all()
            raise

    def service_command(self, name):
        command = [sys.executable, "--service", name] if getattr(sys, "frozen", False) else \
                  [sys.executable, "-u", str(ROOT / "service.py"), name]
        command += ["--data-dir", str(self.data_dir), "--parent-stdio"]
        with self.condition:
            if name in ("evaluation", "planning"):
                require("knowledge" in self.urls, "service_dependency_unavailable", 503)
                command += ["--knowledge-url", self.urls["knowledge"]]
            if name == "evaluation":
                require("profile" in self.urls, "service_dependency_unavailable", 503)
                command += ["--profile-url", self.urls["profile"]]
        return command

    @staticmethod
    def stop_child(process, timeout):
        if process.stdin:
            try:
                process.stdin.close()
            except (OSError, ValueError):
                pass
        try:
            process.wait(timeout=max(.01, timeout))
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
        if process.stdout:
            try:
                process.stdout.close()
            except (OSError, ValueError):
                pass

    def stop(self):
        with self.condition:
            self.stopping = True
            for record in self.records.values():
                record["state"] = "stopping"
                record.pop("historical_only", None)
            children = list(self.children)
            gateway, self.gateway = self.gateway, None
            self.condition.notify_all()
        if gateway:
            gateway.shutdown()
            gateway.server_close()
        for process in children:
            if process.stdin:
                try:
                    process.stdin.close()
                except (OSError, ValueError):
                    pass
        deadline = time.monotonic() + 4
        for process in children:
            self.stop_child(process, deadline - time.monotonic())
        if self.core_thread and self.core_thread is not threading.current_thread():
            self.core_thread.join(timeout=max(.01, deadline - time.monotonic()))
        with self.condition:
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
    parser.add_argument("--startup-policy", choices=("eager", "on-demand"), default="eager")
    args = parser.parse_args()
    stopped = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    runtime = Runtime(args.data_dir, startup_policy=args.startup_policy)
    try:
        runtime.start()
        # IPC readiness carries the credential only to an owning parent, never to normal logs.
        if args.stdio_control:
            status = runtime.status()
            print(canonical({"url": runtime.gateway.url, "token": runtime.token,
                             "pids": [p.pid for p in runtime.children], "startup_policy": args.startup_policy,
                             "timings": status["timings"]}), flush=True)
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
