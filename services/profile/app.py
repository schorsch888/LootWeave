"""Append-only Profile API with optimistic revisions and idempotent confirmation."""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path

from contracts import DomainError, canonical, digest, identifier, require
from storage import connect, initialize
from services.profile.domain import (
    build_fingerprint, ensure_observation_binding, observation_capture_time, observation_time_status, snapshot,
)
from services.profile.live import draft as live_draft, normalize_sample, observation as live_observation
from services.profile.live_cache import LiveInputCache, ObservationCache


class Profile:
    def __init__(self, data_dir: Path):
        self.database = data_dir / "profile.sqlite3"
        self.live_reads = ObservationCache()
        self.live_inputs = LiveInputCache()
        initialize(self.database, """
            CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions (
                profile_id TEXT, revision INTEGER, payload TEXT NOT NULL,
                PRIMARY KEY (profile_id, revision));
            CREATE TABLE IF NOT EXISTS confirmations (
                request_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                profile_id TEXT, revision INTEGER);
        """)

    def connect(self):
        return connect(self.database)

    def handle(self, method, path, body):
        if method == "GET" and path == "/v1/health":
            return {"service": "profile", "contract_version": 1}
        if method == "GET" and path == "/v1/profiles":
            return self.list_profiles()
        if method == "POST" and path == "/v1/snapshots/validate":
            snapshot(body.get("facts"))
            return {"valid": True}
        if method == "POST" and path == "/v1/observations":
            return self.observe(body)
        if method == "POST" and path == "/v1/confirmations":
            return self.confirm(body)
        if method == "POST" and path == "/v1/live/samples":
            return self.publish_live(body)
        if method == "GET" and path == "/v1/live/sources":
            return {"sources": self.live_inputs.sources()}
        if method == "POST" and path == "/v1/imports/live/read":
            return self.read_live(body)
        if method == "POST" and path == "/v1/imports/live/draft":
            return self.draft_live(body)
        parts = path.strip("/").split("/")
        if method == "GET" and len(parts) == 5 and parts[:2] == ["v1", "profiles"] and parts[3] == "revisions":
            profile_id = identifier(parts[2])
            require(parts[4].isdigit(), "revision_required")
            return self.read(profile_id, int(parts[4]))
        if method == "GET" and len(parts) == 3 and parts[:2] == ["v1", "observations"]:
            with self.connect() as db:
                row = db.execute("SELECT payload FROM observations WHERE id=?",
                                 (identifier(parts[2]),)).fetchone()
            require(row is not None, "observation_not_found", 404)
            return json.loads(row[0])
        raise DomainError("not_found", 404)

    def list_profiles(self, limit=20):
        """Return each profile's highest revision, ordered by its row write time."""
        require(type(limit) is int and 1 <= limit <= 100, "profile_limit_invalid")
        with self.connect() as db:
            rows = db.execute("""
                SELECT revision.payload
                FROM revisions AS revision
                JOIN (
                    SELECT profile_id, MAX(revision) AS revision
                    FROM revisions
                    GROUP BY profile_id
                ) AS latest
                  ON latest.profile_id=revision.profile_id
                 AND latest.revision=revision.revision
                ORDER BY revision.rowid DESC
                LIMIT ?
            """, (limit,)).fetchall()
        profiles = []
        for (encoded,) in rows:
            result = json.loads(encoded)
            facts = result["facts"]
            profiles.append({
                "profile_id": result["profile_id"],
                "revision": result["revision"],
                "candidate_name": facts["candidate_item"].get("name", ""),
                "class_id": facts["class_id"],
                "game_id": facts["context"]["game_id"],
            })
        return {"profiles": profiles, "limit": limit}

    def observe(self, body):
        observation_id = identifier(body.get("observation_id"))
        require(body.get("method") in ("text", "ocr"), "observation_method_required")
        if body["method"] == "ocr":
            require(isinstance(body.get("image_ref"), str) and body["image_ref"].startswith("capture://"),
                    "ocr_region_source_required")
        require(isinstance(body.get("raw_text"), str) and 0 <= len(body["raw_text"]) <= 65536,
                "observation_text_required")
        require(body["method"] == "ocr" or bool(body["raw_text"]), "observation_text_required")
        observation_capture_time(body)
        return self.store_observation({**body, "state": "unconfirmed"})

    def store_observation(self, payload):
        observation_id = identifier(payload.get("observation_id"))
        encoded = canonical(payload)
        with self.connect() as db:
            old = db.execute("SELECT payload FROM observations WHERE id=?", (observation_id,)).fetchone()
            require(old is None or old[0] == encoded, "observation_id_conflict", 409)
            db.execute("INSERT OR IGNORE INTO observations VALUES (?,?)", (observation_id, encoded))
        return payload

    def publish_live(self, body):
        sample = normalize_sample(body)
        self.live_inputs.publish(sample["producer_id"], sample)
        return {"producer_id": sample["producer_id"], "captured_at": sample["captured_at"],
                "sample_hash": sample["sample_hash"], "state": "unconfirmed"}

    def capture_live(self, body):
        require(set(body) <= {"observation_id", "producer_id", "context", "class_id", "scope_confirmed",
                             "previous_content_hash"}, "live_request_invalid")
        require(body.get("scope_confirmed") is True, "live_scope_confirmation_required")
        observation_id = identifier(body.get("observation_id"))
        producer = identifier(body.get("producer_id"))
        sample = self.live_inputs.get(producer)
        require(sample is not None, "live_source_missing", 404)
        return live_observation(sample, observation_id, body.get("context"), body.get("class_id"))

    def read_live(self, body):
        previous_hash = body.get("previous_content_hash")
        require(previous_hash is None or isinstance(previous_hash, str)
                and re.fullmatch(r"[0-9a-f]{64}", previous_hash), "live_request_invalid")
        observation = self.capture_live(body)
        encoded = canonical(observation)
        identity = observation["observation_id"]
        with self.connect() as db:
            old = db.execute("SELECT payload FROM observations WHERE id=?", (identity,)).fetchone()
        require(old is None or old[0] == encoded, "observation_id_conflict", 409)
        self.live_reads.put(identity, encoded)
        if previous_hash == observation["source"]["content_hash"]:
            return {"unchanged": True, **{key: observation[key] for key in (
                "observation_id", "source", "capture_context", "raw_text")}}
        return observation

    def draft_live(self, body):
        require(set(body) <= {"observation_id", "candidate_id", "target_slot"}, "live_request_invalid")
        observation_id = identifier(body.get("observation_id"))
        identifier(body.get("candidate_id"))
        with self.connect() as db:
            row = db.execute("SELECT payload FROM observations WHERE id=?", (observation_id,)).fetchone()
        observation = json.loads(row[0]) if row is not None else self.live_reads.get(observation_id)
        require(observation is not None, "live_preview_expired", 404)
        facts = snapshot(live_draft(observation, body["candidate_id"], body.get("target_slot")))
        self.store_observation(observation)
        return {"observation_id": observation_id, "response_hash": observation["source"]["response_hash"],
                "facts": facts, "state": "unconfirmed"}

    def confirm(self, body):
        request_id = identifier(body.get("request_id"))
        profile_id = identifier(body.get("profile_id"))
        observation_id = identifier(body.get("observation_id"))
        require(body.get("player_confirmed") is True, "player_confirmation_required")
        expected = body.get("expected_revision")
        require(type(expected) is int and expected >= 0, "expected_revision_required")
        facts = snapshot(deepcopy(body.get("facts")))
        request_hash = digest(body)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT request_hash, profile_id, revision FROM confirmations WHERE request_id=?",
                                  (request_id,)).fetchone()
            if previous:
                require(previous[0] == request_hash, "idempotency_conflict", 409)
                return self.read(previous[1], previous[2], db)
            observation = db.execute("SELECT payload FROM observations WHERE id=?", (observation_id,)).fetchone()
            require(observation is not None, "observation_not_found", 404)
            ensure_observation_binding(json.loads(observation[0]), facts)
            refs = {e["source_ref"] for e in facts["evidence"]}
            require("observation://" + observation_id in refs, "observation_evidence_required")
            current = db.execute("SELECT COALESCE(MAX(revision),0) FROM revisions WHERE profile_id=?",
                                 (profile_id,)).fetchone()[0]
            require(current == expected, "revision_conflict", 409)
            revision = current + 1
            result = {"contract_version": 1, "profile_id": profile_id, "revision": revision,
                      "observation_id": observation_id, "facts": facts, "facts_hash": digest(facts),
                      "build_hash": build_fingerprint(facts)}
            db.execute("INSERT INTO revisions VALUES (?,?,?)", (profile_id, revision, canonical(result)))
            db.execute("INSERT INTO confirmations VALUES (?,?,?,?)", (request_id, request_hash, profile_id, revision))
            return self.read(profile_id, revision, db)

    def read(self, profile_id: str, revision: int, db=None):
        if db is None:
            with self.connect() as connection:
                return self.read(profile_id, revision, connection)
        row = db.execute("SELECT payload FROM revisions WHERE profile_id=? AND revision=?",
                         (profile_id, revision)).fetchone()
        require(row is not None, "revision_not_found", 404)
        result = json.loads(row[0])
        require(digest(result["facts"]) == result["facts_hash"], "profile_integrity_error", 409)
        # A legacy payload may contain previously untyped inventory extensions.
        # Validate the current wire shape before serving them as confirmed facts.
        if any(key in result["facts"] for key in ("inventory_items", "owned_resources", "preparation_options")):
            snapshot(result["facts"])
        # Additive wire metadata for older v1 records; stored facts remain immutable.
        expected_build = build_fingerprint(result["facts"])
        require(result.get("build_hash", expected_build) == expected_build, "profile_integrity_error", 409)
        result.setdefault("build_hash", expected_build)
        original = db.execute("SELECT payload FROM observations WHERE id=?", (result["observation_id"],)).fetchone()
        try:
            status = observation_time_status(json.loads(original[0]), result["facts"]) if original else "unavailable"
        except (DomainError, KeyError, TypeError, ValueError):
            status = "unavailable"
        # Derived wire status never rewrites the historical revision or its facts hash.
        result["observation_time_status"] = status
        return result
