"""Evaluation fetches versioned APIs, owns its database, and replays frozen inputs."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import DomainError, canonical, digest, identifier, require
from services.evaluation.domain import EVALUATOR_VERSION, EVALUATOR_VERSIONS, evaluate, intent
from storage import connect, initialize


class Evaluation:
    def __init__(self, data_dir: Path, profile_client, knowledge_client):
        self.database = data_dir / "evaluation.sqlite3"
        self.profile, self.knowledge = profile_client, knowledge_client
        initialize(self.database, """
            CREATE TABLE IF NOT EXISTS evaluations (
                id TEXT PRIMARY KEY, request_hash TEXT NOT NULL,
                inputs TEXT NOT NULL, result TEXT NOT NULL, result_hash TEXT NOT NULL);
        """)

    def handle(self, method, path, body):
        if method == "GET" and path == "/v1/health":
            return {"service": "evaluation", "contract_version": 1, "evaluator_version": EVALUATOR_VERSION}
        if method == "POST" and path == "/v1/evaluations":
            return self.create(body)
        if method == "GET" and path == "/v1/evaluations":
            return self.recent()
        parts = path.strip("/").split("/")
        if len(parts) in (3, 4) and parts[:2] == ["v1", "evaluations"]:
            evaluation_id = identifier(parts[2])
            if method == "GET" and len(parts) == 3:
                return self.read(evaluation_id)
            if method == "POST" and len(parts) == 4 and parts[3] == "replay":
                return self.replay(evaluation_id)
        raise DomainError("not_found", 404)

    def create(self, body):
        evaluation_id = identifier(body.get("request_id"))
        profile_id = identifier(body.get("profile_id"))
        pack_id, pack_version = identifier(body.get("pack_id")), identifier(body.get("pack_version"))
        require(type(body.get("profile_revision")) is int and body["profile_revision"] > 0,
                "profile_revision_required")
        require(isinstance(body.get("pack_hash"), str) and len(body["pack_hash"]) == 64,
                "pack_hash_required")
        request_hash = digest(body)
        with connect(self.database) as db:
            old = db.execute("SELECT request_hash,result,result_hash FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
            if old:
                require(old[0] == request_hash, "idempotency_conflict", 409)
                stored = json.loads(old[1])
                require(digest(stored) == old[2], "evaluation_integrity_error", 409)
                return stored
        purpose = intent(body.get("intent"))
        profile = self.profile.call("GET", f"/v1/profiles/{profile_id}/revisions/{body['profile_revision']}")
        require(profile.get("observation_time_status", "not_recorded") in ("verified", "not_recorded"),
                "profile_observation_time_conflict", 409)
        knowledge = self.knowledge.call("GET", f"/v1/packs/{pack_id}/{pack_version}")
        require(knowledge["pack_hash"] == body["pack_hash"], "pack_hash_conflict", 409)
        require(profile["profile_id"] == profile_id and profile["revision"] == body["profile_revision"],
                "profile_revision_conflict", 409)
        result = {"evaluation_id": evaluation_id, **evaluate(profile, knowledge, purpose)}
        inputs = {"profile": profile, "knowledge": knowledge, "intent": purpose,
                  "evaluator_version": EVALUATOR_VERSION}
        with connect(self.database) as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute("SELECT request_hash,result,result_hash FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
            if old:
                require(old[0] == request_hash, "idempotency_conflict", 409)
                stored = json.loads(old[1])
                require(digest(stored) == old[2], "evaluation_integrity_error", 409)
                return stored
            db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?)",
                       (evaluation_id, request_hash, canonical(inputs), canonical(result), digest(result)))
        return result

    def recent(self):
        with connect(self.database) as db:
            rows = db.execute("SELECT id,result,result_hash FROM evaluations ORDER BY rowid DESC LIMIT 100").fetchall()
        summaries = []
        for evaluation_id, encoded, expected in rows:
            result = json.loads(encoded)
            require(digest(result) == expected, "evaluation_integrity_error", 409)
            summaries.append({"evaluation_id": evaluation_id, "retention": result["retention"], "pin": result["pin"]})
        return {"evaluations": summaries, "limit": 100}

    def read(self, evaluation_id):
        with connect(self.database) as db:
            row = db.execute("SELECT result,result_hash FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
        require(row is not None, "evaluation_not_found", 404)
        result = json.loads(row[0])
        require(digest(result) == row[1], "evaluation_integrity_error", 409)
        return result

    def replay(self, evaluation_id):
        with connect(self.database) as db:
            row = db.execute("SELECT inputs FROM evaluations WHERE id=?", (evaluation_id,)).fetchone()
        require(row is not None, "evaluation_not_found", 404)
        inputs = json.loads(row[0])
        require(inputs["evaluator_version"] in EVALUATOR_VERSIONS, "evaluator_version_unavailable", 409)
        replayed = {"evaluation_id": evaluation_id,
                    **evaluate(inputs["profile"], inputs["knowledge"], inputs["intent"],
                               evaluator_version=inputs["evaluator_version"])}
        require(replayed == self.read(evaluation_id), "replay_mismatch", 409)
        return {"identical": True, "result": replayed}
