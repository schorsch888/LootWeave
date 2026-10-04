"""Private, bounded owner control over inherited pipes; no business rules."""
from __future__ import annotations

import os
import queue
import threading
import time
import uuid

from contracts import DomainError, canonical, parse_json, require

SERVICES = ("profile", "knowledge", "evaluation", "planning", "ocr")
CORE_SERVICES = SERVICES[:3]
CONTROL_VERSION = 1
CONTROL_LIMIT = 4096
START_TIMEOUT = 8.0


class StdioOwner:
    """Gateway talks only to its owning Rust supervisor through inherited handles."""

    def __init__(self, source, destination):
        self.source, self.destination = source, destination
        self.pending = {}
        self.lock = threading.Lock()
        self.outgoing = queue.Queue(maxsize=32)
        self.closed = False

    def listen(self, on_close):
        def write():
            try:
                while True:
                    item = self.outgoing.get()
                    with self.lock:
                        if self.closed:
                            break
                        if item is None or item[0] not in self.pending:
                            continue
                    frame = item[1]
                    try:
                        descriptor = self.destination.fileno()
                    except (AttributeError, OSError, ValueError):
                        descriptor = None
                    if descriptor is None:
                        self.destination.write(frame)
                        self.destination.flush()
                    else:
                        # Raw writes avoid holding buffered stdout locks at exit.
                        while frame:
                            written = os.write(descriptor, frame)
                            if not written:
                                raise OSError("owner pipe closed")
                            frame = frame[written:]
            except (OSError, ValueError):
                self.close()
                on_close()

        def read():
            try:
                while True:
                    line = self.source.readline(CONTROL_LIMIT + 1)
                    if not line:
                        break
                    require(len(line) <= CONTROL_LIMIT and line.endswith(b"\n"),
                            "invalid_owner_control", 503)
                    message = parse_json(line)
                    require(isinstance(message, dict) and type(message.get("control_version")) is int
                            and message["control_version"] == CONTROL_VERSION
                            and isinstance(message.get("id"), str), "invalid_owner_control", 503)
                    with self.lock:
                        waiter = self.pending.get(message["id"])
                    if waiter:
                        waiter.put_nowait(message)
            except (DomainError, OSError, ValueError, queue.Full):
                pass
            finally:
                self.close()
                on_close()
        threading.Thread(target=write, name="owner-control-writer", daemon=True).start()
        threading.Thread(target=read, name="owner-control", daemon=True).start()

    def close(self):
        with self.lock:
            self.closed = True
            waiters = list(self.pending.values())
        for waiter in waiters:
            try:
                waiter.put_nowait({"error": "service_owner_unavailable"})
            except queue.Full:
                pass
        try:
            self.outgoing.put_nowait(None)
        except queue.Full:
            pass

    def call(self, operation, service=None):
        require(operation in ("status", "ensure"), "invalid_owner_operation")
        if operation == "ensure":
            require(service in SERVICES, "unsupported_service")
        request_id = uuid.uuid4().hex
        message = {"control_version": CONTROL_VERSION, "id": request_id, "operation": operation}
        if service is not None:
            message["service"] = service
        waiter = queue.Queue(maxsize=1)
        deadline = time.monotonic() + (START_TIMEOUT if operation == "ensure" else 2)
        with self.lock:
            require(not self.closed, "service_owner_unavailable", 503)
            require(len(self.pending) < 32, "service_control_busy", 503)
            self.pending[request_id] = waiter
        try:
            try:
                self.outgoing.put_nowait((request_id, (canonical(message) + "\n").encode("utf-8")))
            except queue.Full:
                raise DomainError("service_control_busy", 503) from None
            try:
                response = waiter.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                raise DomainError("service_start_timeout" if operation == "ensure"
                                  else "service_owner_unavailable", 503) from None
            if "error" in response:
                code = response["error"]
                raise DomainError(code if isinstance(code, str) and len(code) <= 96
                                  else "invalid_owner_control", 503)
            require(isinstance(response.get("result"), dict), "invalid_owner_control", 503)
            return response["result"]
        except (OSError, ValueError):
            raise DomainError("service_owner_unavailable", 503) from None
        finally:
            with self.lock:
                self.pending.pop(request_id, None)

    def status(self):
        return self.call("status")

    def ensure_service(self, name):
        return self.call("ensure", name)
