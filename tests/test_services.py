"""Real loopback integration; Evaluation communicates only via versioned APIs."""
from __future__ import annotations

import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from contracts import DomainError, canonical, digest
from services.evaluation.domain import EVALUATOR_VERSION, evaluate
from test_observation_time import CAPTURE_MS, capture_observation, confirmation, seed_legacy_capture_revision
from services.evaluation.app import Evaluation
from services.knowledge.app import Knowledge
from services.profile.app import Profile
from transport import Client, LocalServer

ROOT = Path(__file__).resolve().parents[1]
TOKEN = "synthetic-test-session-" + "x" * 32
DEMO = json.loads((ROOT / "fixtures/demo.json").read_text(encoding="utf-8"))


class ServiceIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.servers = []
        directory = Path(self.temp.name)
        self.profile = self.start(Profile(directory / "profile"))
        self.knowledge = self.start(Knowledge(ROOT / "knowledge-packs"))
        self.evaluation = self.start(Evaluation(directory / "evaluation", self.profile, self.knowledge))

    def start(self, app):
        server = LocalServer(app, TOKEN)
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        thread.start()
        self.servers.append(server)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return Client(server.url, TOKEN)

    def create_result(self, facts=None, purpose=None):
        self.profile.call("POST", "/v1/observations",
                          {"observation_id": "demo-text", "method": "text", "raw_text": "Synthetic"})
        confirmed = self.profile.call("POST", "/v1/confirmations", {
            "request_id": "confirm", "profile_id": "demo", "observation_id": "demo-text",
            "expected_revision": 0, "player_confirmed": True,
            "facts": copy.deepcopy(DEMO["facts"] if facts is None else facts)})
        catalog = self.knowledge.call("GET", "/v1/packs")
        pack = next(p for p in catalog["packs"] if p["execution_policy"] == "synthetic_only")
        body = {"request_id": "evaluate", "profile_id": "demo", "profile_revision": confirmed["revision"],
                "pack_id": pack["pack_id"], "pack_version": pack["version"],
                "pack_hash": pack["pack_hash"], "intent": copy.deepcopy(DEMO["intent"] if purpose is None else purpose)}
        return body, self.evaluation.call("POST", "/v1/evaluations", body)

    def test_capture_time_conflict_is_http_400_and_corrected_retry_saves_once(self):
        self.profile.call("POST", "/v1/observations", capture_observation(milliseconds=CAPTURE_MS+1))
        body = confirmation()
        with self.assertRaisesRegex(DomainError, "observation_time_conflict") as rejected:
            self.profile.call("POST", "/v1/confirmations", body)
        self.assertEqual(400, rejected.exception.status)
        app = self.servers[0].app
        with app.connect() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0])
        body["facts"]["captured_at"] = "2026-01-01T00:00:00.001Z"
        body["facts"]["evidence"][0]["captured_at"] = "2026-01-01T08:00:00.001+08:00"
        saved = self.profile.call("POST", "/v1/confirmations", body)
        self.assertEqual("verified", saved["observation_time_status"])
        self.assertEqual(saved, self.profile.call("POST", "/v1/confirmations", body))
        self.assertEqual(body["facts"], saved["facts"])
        with app.connect() as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0])

    def test_legacy_source_time_blocks_new_evaluation_but_frozen_history_replays(self):
        _, original, profile_payload = seed_legacy_capture_revision(self.servers[0].app)
        returned = self.profile.call("GET", "/v1/profiles/demo/revisions/1")
        self.assertEqual("conflict", returned["observation_time_status"])
        knowledge = self.knowledge.call("GET", "/v1/packs/synthetic-leveling/1.0.0")
        body = {"request_id": "legacy-clock-evaluation", "profile_id": "demo", "profile_revision": 1,
                "pack_id": "synthetic-leveling", "pack_version": "1.0.0", "pack_hash": knowledge["pack_hash"],
                "intent": copy.deepcopy(DEMO["intent"])}
        # Reproduce the preceding immutable algorithm on the preceding v1 input shape.
        old_result = {"evaluation_id": body["request_id"], **evaluate(original, knowledge, body["intent"])}
        inputs = {"profile": original, "knowledge": knowledge, "intent": body["intent"], "evaluator_version": EVALUATOR_VERSION}
        app = self.servers[2].app
        from storage import connect
        with connect(app.database) as db:
            db.execute("INSERT INTO evaluations VALUES (?,?,?,?,?)", (body["request_id"], digest(body), canonical(inputs), canonical(old_result), digest(old_result)))
        changed = {**body, "request_id": "new-clock-evaluation"}
        with self.assertRaisesRegex(DomainError, "profile_observation_time_conflict") as rejected:
            self.evaluation.call("POST", "/v1/evaluations", changed)
        self.assertEqual(409, rejected.exception.status)
        self.assertEqual(old_result, self.evaluation.call("POST", "/v1/evaluations", body))
        with self.servers[0].app.connect() as db:
            self.assertEqual(profile_payload, db.execute("SELECT payload FROM revisions").fetchone()[0])
        with connect(app.database) as db:
            self.assertEqual(1, db.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0])
            self.assertEqual(canonical(inputs), db.execute("SELECT inputs FROM evaluations").fetchone()[0])
        self.servers[0].shutdown()
        self.servers[1].shutdown()
        for _ in range(10):
            replay = self.evaluation.call("POST", "/v1/evaluations/legacy-clock-evaluation/replay", {})
            self.assertTrue(replay["identical"])
            self.assertEqual(old_result, replay["result"])

    def test_confirm_evaluate_replay_with_independent_storage(self):
        body, result = self.create_result()
        self.assertEqual("mechanism_loss", result["comparison"]["status"])
        self.assertEqual(result, self.evaluation.call("POST", "/v1/evaluations", body))
        # Historical replay must work after source services are stopped.
        self.servers[0].shutdown()
        self.servers[1].shutdown()
        for _ in range(10):
            replay = self.evaluation.call("POST", "/v1/evaluations/evaluate/replay", {})
            self.assertTrue(replay["identical"])
            self.assertEqual(result, replay["result"])

    def test_unknown_capability_is_not_missing_and_survives_ten_http_replays(self):
        facts, purpose = copy.deepcopy(DEMO["facts"]), copy.deepcopy(DEMO["intent"])
        facts["candidate_item"]["effects"].append("fixture-temporary-focus")
        facts["conditions"]["buff_active"] = "unknown"
        purpose.update(required_capabilities=["temporary_focus"], future_builds=[])
        body, result = self.create_result(facts, purpose)
        self.assertEqual("0.1.8", result["pin"]["evaluator_version"])
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertEqual("blocked", result["comparison"]["status"])
        self.assertEqual([], result["comparison"]["missing_requirements"])
        self.assertEqual([], result["comparison"]["missing_mechanisms"])
        self.assertEqual([{"actor": "hero", "capability": "temporary_focus",
                           "before": "inactive", "after": "unknown"}],
                         result["comparison"]["uncertain_mechanisms"])
        self.assertEqual(["unknown_condition:temporary-focus"], result["blockers"])
        row = next(row for row in result["comparison"]["after"] if row["rule_id"] == "temporary-focus")
        self.assertEqual([facts["candidate_item"]["instance_id"]], row["source_ids"])
        self.assertEqual(["demo-input"], row["input_evidence_ids"])
        self.assertEqual(["fixture-spec"], row["evidence_ids"])
        self.assertEqual(result, self.evaluation.call("POST", "/v1/evaluations", body))
        self.servers[0].shutdown()
        self.servers[1].shutdown()
        for _ in range(10):
            replay = self.evaluation.call("POST", "/v1/evaluations/evaluate/replay", {})
            self.assertTrue(replay["identical"])
            self.assertEqual(result, replay["result"])
            self.assertEqual("0.1.8", replay["result"]["pin"]["evaluator_version"])

    def test_confirmed_effect_owners_and_embedded_default_survive_http_replay(self):
        facts = copy.deepcopy(DEMO["facts"])
        candidate = facts["candidate_item"]
        candidate["effects"] = []
        candidate["embedded_items"] = [{"id": "socketed", "effects": ["fixture-vitality-support"],
                                         "evidence_ids": ["demo-input"]}]
        for rune in facts["runes"]:
            rune.update(actor="companion", companion_id=facts["companions"][0]["id"])
        body, result = self.create_result(facts)
        self.assertEqual("0.1.8", result["pin"]["evaluator_version"])
        self.assertEqual("keep", result["retention"])
        for phase in ("before", "after"):
            frost = next(row for row in result["comparison"][phase] if row["rule_id"] == "frost-two")
            self.assertEqual("inactive", frost["state"])
            self.assertEqual([], frost["source_ids"])
        vitality = next(row for row in result["comparison"]["after"] if row["rule_id"] == "vitality-support")
        self.assertEqual("active", vitality["state"])
        self.assertEqual([candidate["instance_id"] + ":socketed"], vitality["source_ids"])
        self.assertEqual(["demo-input"], vitality["input_evidence_ids"])
        self.assertEqual(result, self.evaluation.call("POST", "/v1/evaluations", body))
        self.servers[0].shutdown()
        self.servers[1].shutdown()
        for _ in range(10):
            replay = self.evaluation.call("POST", "/v1/evaluations/evaluate/replay", {})
            self.assertTrue(replay["identical"])
            self.assertEqual(result, replay["result"])

    def test_companion_cannot_supply_a_hero_requirement_over_http(self):
        facts, purpose = copy.deepcopy(DEMO["facts"]), copy.deepcopy(DEMO["intent"])
        facts["candidate_item"] = copy.deepcopy(facts["equipped_items"]["weapon"])
        facts["candidate_item"]["instance_id"] = "same-mechanisms-candidate"
        purpose["required_capabilities"] = ["companion_support"]
        body, result = self.create_result(facts, purpose)
        comparison = result["comparison"]
        self.assertEqual("mechanism_loss", comparison["status"])
        self.assertEqual([], comparison["lost_mechanisms"])
        self.assertEqual([], comparison["gained_mechanisms"])
        self.assertEqual(["companion_support"], comparison["missing_requirements"])
        self.assertEqual([{"actor": "hero", "capability": "companion_support"}],
                         comparison["missing_mechanisms"])
        for phase in ("before", "after"):
            rule = next(row for row in comparison[phase] if row["rule_id"] == "companion-support")
            self.assertEqual("companion", rule["actor"])
            self.assertEqual("active", rule["state"])
        self.assertEqual(result, self.evaluation.call("POST", "/v1/evaluations", body))
        self.servers[0].shutdown()
        self.servers[1].shutdown()
        for _ in range(10):
            replay = self.evaluation.call("POST", "/v1/evaluations/evaluate/replay", {})
            self.assertTrue(replay["identical"])
            self.assertEqual(result, replay["result"])

    def test_unmapped_goal_is_uncertain_not_a_missing_mechanism_over_http(self):
        purpose = copy.deepcopy(DEMO["intent"])
        purpose["required_capabilities"] = ["unmapped-resource-cycle", "unmapped-resource-cycle"]
        body, result = self.create_result(purpose=purpose)
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertEqual(["unknown_required_capability:unmapped-resource-cycle"], result["blockers"])
        self.assertEqual("blocked", result["comparison"]["status"])
        self.assertIs(result["comparison"]["scope_compatible"], True)
        self.assertEqual([], result["comparison"]["missing_requirements"])
        self.assertEqual([], result["comparison"]["missing_mechanisms"])
        self.assertEqual(result, self.evaluation.call("POST", "/v1/evaluations", body))
        self.servers[0].shutdown()
        self.servers[1].shutdown()
        for _ in range(10):
            replay = self.evaluation.call("POST", "/v1/evaluations/evaluate/replay", {})
            self.assertTrue(replay["identical"])
            self.assertEqual(result, replay["result"])

    def test_same_evaluation_id_with_different_intent_is_rejected(self):
        body, _result = self.create_result()
        body["intent"] = copy.deepcopy(body["intent"])
        body["intent"]["revision"] = 2
        with self.assertRaisesRegex(DomainError, "idempotency_conflict"):
            self.evaluation.call("POST", "/v1/evaluations", body)

    def test_pack_hash_cannot_silently_change(self):
        body, _result = self.create_result()
        body.update(request_id="other", pack_hash="0" * 64)
        with self.assertRaisesRegex(DomainError, "pack_hash_conflict"):
            self.evaluation.call("POST", "/v1/evaluations", body)

    def test_unauthenticated_health_is_rejected(self):
        with self.assertRaisesRegex(DomainError, "unauthorized"):
            Client(self.profile.url, "wrong").call("GET", "/v1/health")

    def test_browser_origin_is_checked_even_with_valid_token(self):
        opener = build_opener(ProxyHandler({}))
        request = Request(self.profile.url + "/v1/health",
                          headers={"Authorization": "Bearer " + TOKEN, "Origin": "https://example.invalid"})
        with self.assertRaises(HTTPError) as raised:
            opener.open(request)
        self.assertEqual(403, raised.exception.code)

    def test_host_header_prevents_dns_rebinding(self):
        opener = build_opener(ProxyHandler({}))
        request = Request(self.profile.url + "/v1/health",
                          headers={"Authorization": "Bearer " + TOKEN, "Host": "example.invalid"})
        with self.assertRaises(HTTPError) as raised:
            opener.open(request)
        self.assertEqual(403, raised.exception.code)

    def test_non_loopback_service_url_is_rejected(self):
        for url in ("https://127.0.0.1:1234", "http://localhost:1234", "http://example.invalid:1234",
                    "http://user:pass@127.0.0.1:1234", "http://127.0.0.1:1234/path"):
            with self.subTest(url=url), self.assertRaises(DomainError):
                Client(url, TOKEN)

    def test_research_versions_are_explicit_and_api_copies_are_immutable(self):
        catalog = self.knowledge.call("GET", "/v1/packs")
        versions = {p["version"] for p in catalog["packs"] if p["pack_id"] == "deskrawl-sorcerer-leveling"}
        self.assertEqual({
            "0.1.0-research", "0.2.0-research", "0.3.0-research", "0.4.0-research",
            "0.5.0-research", "0.6.0-research", "0.7.0-research",
        }, versions)
        for version in sorted(versions):
            with self.subTest(version=version):
                path = "/v1/packs/deskrawl-sorcerer-leveling/" + version
                first = self.knowledge.call("GET", path)
                original = copy.deepcopy(first)
                first["pack"]["rules"].append({"id": "untrusted"})
                first["pack"]["evidence"].clear()
                self.assertEqual(original, self.knowledge.call("GET", path))
        with self.assertRaisesRegex(DomainError, "pack_version_not_found"):
            self.knowledge.call("GET", "/v1/packs/deskrawl-sorcerer-leveling/latest")

    def test_research_evaluation_and_replay_keep_mechanics_blocked_over_http(self):
        pack = self.knowledge.call("GET", "/v1/packs/deskrawl-sorcerer-leveling/0.7.0-research")
        facts = copy.deepcopy(DEMO["facts"])
        facts["context"] = copy.deepcopy(pack["pack"]["context"])
        facts["evidence"][0]["source_ref"] = "observation://research-text"
        self.profile.call("POST", "/v1/observations",
                          {"observation_id": "research-text", "method": "text", "raw_text": "Synthetic research input"})
        confirmed = self.profile.call("POST", "/v1/confirmations", {
            "request_id": "research-confirm", "profile_id": "research", "observation_id": "research-text",
            "expected_revision": 0, "player_confirmed": True, "facts": facts})
        result = self.evaluation.call("POST", "/v1/evaluations", {
            "request_id": "research-evaluate", "profile_id": "research", "profile_revision": confirmed["revision"],
            "pack_id": pack["pack"]["pack_id"], "pack_version": pack["pack"]["version"],
            "pack_hash": pack["pack_hash"], "intent": copy.deepcopy(DEMO["intent"])})
        self.assertIn("game_mechanics_not_accepted", result["blockers"])
        self.assertEqual("needs_confirmation", result["retention"])
        self.assertEqual([], result["comparison"]["before"])
        self.assertEqual([], result["comparison"]["after"])
        self.assertEqual("0.7.0-research", result["pin"]["pack_version"])
        self.servers[0].shutdown()
        self.servers[1].shutdown()
        for _ in range(10):
            replay = self.evaluation.call("POST", "/v1/evaluations/research-evaluate/replay", {})
            self.assertTrue(replay["identical"])
            self.assertEqual(result, replay["result"])


if __name__ == "__main__":
    unittest.main()
