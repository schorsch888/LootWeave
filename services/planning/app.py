"""Planning owns historical trials. It queries Knowledge through its API."""
from __future__ import annotations

import json
from pathlib import Path

from contracts import DomainError, canonical, digest, identifier, require
from services.planning.domain import compare_routes, drop_estimate, eligibility, trial
from storage import connect, initialize


class Planning:
    def __init__(self, data_dir: Path, knowledge_client):
        self.database = data_dir / "planning.sqlite3"
        self.knowledge = knowledge_client
        initialize(self.database, "CREATE TABLE IF NOT EXISTS trials (id TEXT PRIMARY KEY, payload TEXT NOT NULL);")

    def handle(self, method, path, body):
        if method == "GET" and path == "/v1/health":
            return {"service": "planning", "contract_version": 1}
        if method == "POST" and path == "/v1/trials":
            measured = trial(body)
            trial_id = identifier(measured["trial_id"])
            encoded = canonical(measured)
            with connect(self.database) as db:
                db.execute("BEGIN IMMEDIATE")
                old = db.execute("SELECT payload FROM trials WHERE id=?", (trial_id,)).fetchone()
                if old is not None:
                    # Retry identity belongs to the recorded inputs, not derived classification.
                    inputs = lambda value: {key: entry for key, entry in value.items()
                                            if key not in ("measurement_status", "unknowns")}
                    require(canonical(inputs(json.loads(old[0]))) == canonical(inputs(measured)),
                            "trial_id_conflict", 409)
                else:
                    require("trial_measurement_out_of_range" not in measured["unknowns"],
                            "trial_measurement_out_of_range")
                    db.execute("INSERT INTO trials VALUES (?,?)", (trial_id, encoded))
            return measured
        if method == "POST" and path == "/v1/routes/compare":
            with connect(self.database) as db:
                trials = [json.loads(row[0]) for row in db.execute("SELECT payload FROM trials ORDER BY id")]
            return compare_routes(body.get("scope"), body.get("candidates"), trials)
        if method == "POST" and path == "/v1/sources/eligibility":
            pack_id, version = identifier(body.get("pack_id")), identifier(body.get("pack_version"))
            knowledge = self.knowledge.call("GET", f"/v1/packs/{pack_id}/{version}")
            require(knowledge["pack_hash"] == body.get("pack_hash"), "pack_hash_conflict", 409)
            return eligibility(body.get("facts"), knowledge["pack"])
        if method == "POST" and path == "/v1/drop-estimates":
            return drop_estimate(body)
        raise DomainError("not_found", 404)
