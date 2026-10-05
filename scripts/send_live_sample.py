"""Send independent observation JSON to the existing local runtime."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from contracts import DomainError, parse_json, require
from transport import NoRedirect

LIMIT = 4 * 1024 * 1024


def send(gateway, credential, raw):
    url = urlsplit(gateway)
    require(url.scheme == "http" and url.hostname == "127.0.0.1" and url.port is not None
            and 1024 <= url.port <= 65535 and url.path in ("", "/")
            and not url.username and not url.password and not url.query and not url.fragment, "local_runtime_url_required")
    require(isinstance(credential, str) and 24 <= len(credential) <= 1024, "local_session_required")
    require(0 < len(raw) <= LIMIT, "live_sample_too_large")
    value = parse_json(raw)
    require(value.get("schema") == "lootweave-live/1", "live_schema_unsupported")
    request = Request(f"http://127.0.0.1:{url.port}/api/profile/live/samples", data=raw, method="POST",
                      headers={"Authorization": "Bearer " + credential, "Content-Type": "application/json"})
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        with opener.open(request, timeout=5) as response:
            reply = response.read(65537)
            require(len(reply) <= 65536, "local_response_invalid")
            result = parse_json(reply)
            require(result.get("state") == "unconfirmed", "local_response_invalid")
            return {"state": "unconfirmed", "sample_hash": result.get("sample_hash")}
    except HTTPError as error:
        try:
            code = parse_json(error.read(65536)).get("error")
            require(isinstance(code, str) and code.replace("_", "").isalnum(), "local_response_invalid")
        except (DomainError, ValueError):
            code = "local_response_invalid"
        raise DomainError(code) from None
    except (URLError, TimeoutError, OSError):
        raise DomainError("local_runtime_unavailable") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway", required=True)
    parser.add_argument("--file", type=Path)
    args = parser.parse_args()
    try:
        credential = os.environ.get("LOOTWEAVE_LIVE_SESSION", "")
        if args.file:
            with args.file.open("rb") as source:
                print(json.dumps(send(args.gateway, credential, source.read(LIMIT + 1))))
        else:
            while raw := sys.stdin.buffer.readline(LIMIT + 1):
                if raw.strip():
                    print(json.dumps(send(args.gateway, credential, raw)), flush=True)
    except (DomainError, ValueError, OSError) as error:
        print(error.code if isinstance(error, DomainError) else "local_input_invalid", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
