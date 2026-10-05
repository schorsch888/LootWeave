"""Bound temporary reads without changing durable observations or revisions."""
from __future__ import annotations

import json
from collections import OrderedDict
from threading import Lock
from time import monotonic

from contracts import canonical, require


class ObservationCache:
    def __init__(self, max_entries=16, max_bytes=8 * 1024 * 1024, ttl=600):
        self.max_entries, self.max_bytes, self.ttl = max_entries, max_bytes, ttl
        self.rows = OrderedDict()
        self.bytes = 0
        self.lock = Lock()

    def discard(self, identity):
        self.bytes -= self.rows.pop(identity)[2]

    def expire(self, now):
        for identity, (_, expires, _) in list(self.rows.items()):
            if expires <= now:
                self.discard(identity)

    def put(self, identity, encoded):
        size = len(encoded.encode("utf-8"))
        require(size <= self.max_bytes, "live_sample_too_large", 502)
        with self.lock:
            now = monotonic()
            self.expire(now)
            previous = self.rows.get(identity)
            require(previous is None or previous[0] == encoded, "observation_id_conflict", 409)
            if previous is not None:
                return
            while self.rows and (len(self.rows) >= self.max_entries or self.bytes + size > self.max_bytes):
                self.discard(next(iter(self.rows)))
            self.rows[identity] = (encoded, now + self.ttl, size)
            self.bytes += size

    def get(self, identity):
        with self.lock:
            self.expire(monotonic())
            row = self.rows.get(identity)
            if row is not None:
                self.rows.move_to_end(identity)
        return json.loads(row[0]) if row is not None else None


class LiveInputCache(ObservationCache):
    """Keep the newest sample of each producer without a database write."""
    def publish(self, identity, sample):
        encoded = canonical(sample)
        size = len(encoded.encode("utf-8"))
        require(size <= self.max_bytes, "live_sample_too_large", 502)
        with self.lock:
            now = monotonic()
            self.expire(now)
            old = self.rows.get(identity)
            if old:
                previous = json.loads(old[0])
                require(sample["captured_at"] >= previous["captured_at"], "live_sample_out_of_order", 409)
                if sample["captured_at"] == previous["captured_at"]:
                    require(encoded == old[0], "live_sample_time_conflict", 409)
                    return
                self.discard(identity)
            while self.rows and (len(self.rows) >= self.max_entries or self.bytes + size > self.max_bytes):
                self.discard(next(iter(self.rows)))
            self.rows[identity] = (encoded, now + self.ttl, size)
            self.bytes += size

    def sources(self):
        with self.lock:
            self.expire(monotonic())
            return [{"producer_id": identity, "captured_at": json.loads(row[0])["captured_at"]}
                    for identity, row in self.rows.items()]
