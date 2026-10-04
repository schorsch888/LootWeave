"""Each invocation runs one business capability in one process."""
from __future__ import annotations

import argparse
import os
import sys
import threading
from pathlib import Path

from contracts import DomainError, canonical
from transport import Client, LocalServer
from process_lifecycle import own_service_process

ROOT = Path(__file__).resolve().parent


def create_app(args, token):
    if args.name == "profile":
        from services.profile.app import Profile
        return Profile(args.data_dir / "profile")
    if args.name == "knowledge":
        from services.knowledge.app import Knowledge
        return Knowledge(args.pack_dir)
    if args.name == "evaluation":
        from services.evaluation.app import Evaluation
        return Evaluation(args.data_dir / "evaluation",
                          Client(args.profile_url, token), Client(args.knowledge_url, token))
    if args.name == "planning":
        from services.planning.app import Planning
        return Planning(args.data_dir / "planning", Client(args.knowledge_url, token))
    if args.name == "ocr":
        from services.ocr.app import OCR
        return OCR(args.data_dir / "ocr", args.ocr_command)
    raise DomainError("unsupported_service")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("name", choices=("profile", "knowledge", "evaluation", "planning", "ocr"))
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".local")
    parser.add_argument("--pack-dir", type=Path, default=ROOT / "knowledge-packs")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--profile-url")
    parser.add_argument("--knowledge-url")
    parser.add_argument("--ocr-command")
    parser.add_argument("--parent-stdio", action="store_true")
    args = parser.parse_args()
    token = os.environ.get("LOOTWEAVE_SESSION_TOKEN", "")
    try:
        if os.name == "nt" and os.environ.get("LOOTWEAVE_PARENT_JOB") == "1":
            # The Rust owner assigns its outer job before releasing this byte.
            if not args.parent_stdio or sys.stdin.buffer.read(1) != b"1":
                raise DomainError("service_parent_job_unavailable", 503)
        own_service_process()
        app = create_app(args, token)
        server = LocalServer(app, token, args.port)
        if args.parent_stdio:
            # Closing the supervisor's pipe stops a service even after a supervisor crash.
            def watch_parent():
                sys.stdin.buffer.read()
                server.shutdown()
            threading.Thread(target=watch_parent, daemon=True).start()
        print(canonical({"service": args.name, "url": server.url, "contract_version": 1}), flush=True)
        try:
            server.serve_forever(poll_interval=0.1)
        finally:
            server.server_close()
    except (DomainError, OSError) as error:
        print(canonical({"error": error.code if isinstance(error, DomainError) else "startup_failed"}),
              file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
