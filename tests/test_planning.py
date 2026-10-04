"""Route and source regressions use synthetic measurements, not game performance."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
import math
import secrets
import threading
import tempfile
import unittest
from pathlib import Path

from contracts import DomainError, canonical, parse_json
from services.planning.app import Planning
from storage import connect
from transport import Client, LocalServer
from services.planning.domain import compare_routes, drop_estimate, eligibility, trial

ROOT = Path(__file__).resolve().parents[1]
PACK = json.loads((ROOT / "knowledge-packs/synthetic-leveling-1.0.0.json").read_text())
SCOPE = {"context": PACK["context"], "class_id": "sorcerer", "build_hash": "fixture-build",
         "bonuses_hash": "fixture-bonuses", "objective": "leveling", "level_start": 15,
         "level_end": 15, "xp_kind": "character"}
BASE_TRIAL = {"trial_id": "trial-1", "scope": SCOPE, "map_id": "map-a", "difficulty_id": "normal",
              "access": "active", "xp_gain": 100, "complete_elapsed_seconds": 60,
              "method": "cumulative_xp", "bonuses_unchanged": True, "build_unchanged": True,
              "xp_transition": False, "level_thresholds_verified": False, "evidence_ids": ["synthetic-trial"]}
CANDIDATES = [{"map_id": "map-a", "difficulty_id": "normal", "access": "active"},
              {"map_id": "map-b", "difficulty_id": "normal", "access": "active"}]


class RouteTests(unittest.TestCase):
    def test_pooling_is_total_xp_over_total_time_not_mean_of_rates(self):
        slow = {**BASE_TRIAL, "trial_id": "slow", "xp_gain": 100, "complete_elapsed_seconds": 600}
        result = compare_routes(SCOPE, CANDIDATES, [BASE_TRIAL, slow])
        self.assertAlmostEqual(200 * 60 / 660, result["routes"][0]["xp_per_minute"])
        self.assertEqual("trial_candidate", result["routes"][1]["status"])
        self.assertIsNone(result["routes"][1]["xp_per_minute"])

    def test_unmeasured_maps_are_not_inferred_from_levels(self):
        result = compare_routes(SCOPE, CANDIDATES, [])
        self.assertIsNone(result["best_measured_candidate"])
        self.assertTrue(all(r["status"] == "trial_candidate" for r in result["routes"]))

    def test_unknown_and_inaccessible_entrances_are_excluded(self):
        candidates = copy.deepcopy(CANDIDATES)
        candidates[0]["access"] = "unknown"
        candidates[1]["access"] = "inactive"
        result = compare_routes(SCOPE, candidates, [BASE_TRIAL])
        self.assertIsNone(result["best_measured_candidate"])
        self.assertEqual("needs_confirmation", result["routes"][0]["status"])
        self.assertEqual("inaccessible", result["routes"][1]["status"])

    def test_level_up_bar_difference_requires_verified_thresholds(self):
        data = copy.deepcopy(BASE_TRIAL)
        data["method"] = "bar_difference"
        data["scope"]["level_end"] = 16
        self.assertEqual("uncertain", trial(data)["measurement_status"])
        data["level_thresholds_verified"] = True
        self.assertEqual("confirmed", trial(data)["measurement_status"])

    def test_cumulative_actual_xp_can_span_level_up(self):
        data = copy.deepcopy(BASE_TRIAL)
        data["scope"]["level_end"] = 16
        self.assertEqual("confirmed", trial(data)["measurement_status"])

    def test_paragon_range_can_start_at_zero_without_using_character_levels(self):
        data = copy.deepcopy(BASE_TRIAL)
        data["scope"].update(xp_kind="paragon", level_start=0, level_end=1)
        measured = trial(data)
        self.assertEqual("confirmed", measured["measurement_status"])
        result = compare_routes(data["scope"], CANDIDATES, [data, BASE_TRIAL])
        self.assertEqual(1, result["routes"][0]["trial_count"])
        self.assertEqual("incomparable_scope", result["excluded_trials"][0]["reason"])
        data["scope"]["level_start"] = -1
        with self.assertRaisesRegex(DomainError, "level_range_required"):
            trial(data)
        data["scope"].update(xp_kind="character", level_start=0)
        with self.assertRaisesRegex(DomainError, "level_range_required"):
            trial(data)

    def test_character_paragon_transition_is_not_pooled(self):
        data = {**BASE_TRIAL, "xp_transition": True}
        self.assertEqual("uncertain", trial(data)["measurement_status"])
        self.assertIsNone(compare_routes(SCOPE, CANDIDATES, [data])["best_measured_candidate"])

    def test_changed_buffs_and_build_are_not_accepted(self):
        for field in ("bonuses_unchanged", "build_unchanged"):
            data = {**BASE_TRIAL, field: False}
            with self.subTest(field=field):
                self.assertEqual("uncertain", trial(data)["measurement_status"])

    def test_incomparable_historical_trial_is_retained_but_excluded(self):
        data = copy.deepcopy(BASE_TRIAL)
        data["scope"]["build_hash"] = "previous-build"
        result = compare_routes(SCOPE, CANDIDATES, [data])
        self.assertEqual("incomparable_scope", result["excluded_trials"][0]["reason"])
        self.assertIsNone(result["best_measured_candidate"])

    def test_negative_xp_and_zero_time_are_rejected(self):
        for field, value in (("xp_gain", -1), ("complete_elapsed_seconds", 0),
                             ("complete_elapsed_seconds", -1), ("complete_elapsed_seconds", float("nan"))):
            with self.subTest(field=field, value=value), self.assertRaises(DomainError):
                trial({**BASE_TRIAL, field: value})

    def test_map_and_difficulty_form_one_candidate(self):
        candidates = [{"map_id": "map-a", "difficulty_id": "normal", "access": "active"},
                      {"map_id": "map-a", "difficulty_id": "hard", "access": "active"}]
        result = compare_routes(SCOPE, candidates, [BASE_TRIAL])
        self.assertEqual(1, result["routes"][0]["trial_count"])
        self.assertEqual(0, result["routes"][1]["trial_count"])

    def test_single_trial_and_close_results_request_retest(self):
        result = compare_routes(SCOPE, CANDIDATES, [BASE_TRIAL])
        self.assertEqual("single_trial", result["routes"][0]["observation"])
        self.assertTrue(result["retest_recommended"])


    def test_unrepresentable_individual_measurements_are_excluded(self):
        for changes in ({"complete_elapsed_seconds": 1e-308}, {"xp_gain": 10**400},
                        {"scope": {**SCOPE, "level_end": 2**53}}):
            with self.subTest(changes=tuple(changes)):
                value = {**BASE_TRIAL, **changes}
                measured = trial(value)
                self.assertEqual("uncertain", measured["measurement_status"])
                self.assertIn("trial_measurement_out_of_range", measured["unknowns"])
                result = compare_routes(SCOPE, CANDIDATES, [value, {**BASE_TRIAL, "trial_id": "good", "map_id": "map-b"}])
                self.assertEqual("map-b", result["best_measured_candidate"]["map_id"])
                self.assertEqual(0, result["routes"][0]["trial_count"])
                self.assertEqual(result, parse_json(canonical(result)))

    def test_aggregate_overflow_is_unknown_and_cannot_establish_zero_rate(self):
        for changes, total in (({"complete_elapsed_seconds": 1e308}, "time_total"),
                               ({"xp_gain": 2**53 - 1}, "xp_total")):
            values = [{**BASE_TRIAL, **changes, "trial_id": "total-" + str(i)} for i in range(2)]
            with self.subTest(total=total):
                result = compare_routes(SCOPE, CANDIDATES, values)
                route = result["routes"][0]
                self.assertEqual("needs_confirmation", route["status"])
                self.assertEqual(["aggregate_trial_measurement_out_of_range"], route["unknowns"])
                self.assertIsNone(route["xp_per_minute"])
                self.assertIsNone(route[total])
                self.assertIsNone(result["best_measured_candidate"])
                self.assertEqual(result, parse_json(canonical(result)))

    def test_finite_numeric_edges_and_true_zero_keep_their_measurements(self):
        for xp, seconds in ((1, 1e-305), (100, 1e308), (2**53 - 1, 60), (0, 1e-308)):
            with self.subTest(xp=xp, seconds=seconds):
                value = {**BASE_TRIAL, "xp_gain": xp, "complete_elapsed_seconds": seconds}
                self.assertEqual("confirmed", trial(value)["measurement_status"])
                route = compare_routes(SCOPE, CANDIDATES, [value])["routes"][0]
                self.assertEqual("measured", route["status"])
                self.assertEqual(xp * 60 / seconds, route["xp_per_minute"])
                self.assertEqual([], route["unknowns"])
                canonical(route)



class EligibilityTests(unittest.TestCase):
    def facts(self):
        return {"context": copy.deepcopy(PACK["context"]), "class_id": "sorcerer",
                "character_level": 15, "conditions": {"entry_unlocked": "active"}}

    def test_source_eligibility_is_separate_from_final_probability(self):
        result = eligibility(self.facts(), PACK)
        self.assertEqual("active", result["sources"][0]["eligibility"])
        self.assertNotIn("probability", result["sources"][0])


for level in (1, 9, 10, 15, 19, 20, 70):
    for state in ("active", "inactive", "unknown"):
        def case(self, character_level=level, entry_state=state):
            facts = self.facts()
            facts["character_level"] = character_level
            facts["conditions"]["entry_unlocked"] = entry_state
            expected = "inactive" if character_level < 10 else entry_state
            self.assertEqual(expected, eligibility(facts, PACK)["sources"][0]["eligibility"])
        setattr(EligibilityTests, f"test_entry_level_{level}_state_{state}", case)

for entitlement in (False, True):
    for state in ("active", "inactive", "unknown"):
        for level in (19, 20):
            def case(self, has_entitlement=entitlement, entry_state=state, character_level=level):
                facts = self.facts()
                facts["character_level"] = character_level
                facts["conditions"]["elite_access"] = entry_state
                if has_entitlement:
                    facts["context"]["content_entitlements"] = ["fixture-expansion"]
                expected = entry_state if has_entitlement and character_level >= 20 else "inactive"
                self.assertEqual(expected, eligibility(facts, PACK)["sources"][1]["eligibility"])
            setattr(EligibilityTests, f"test_elite_level_{level}_entitlement_{entitlement}_state_{state}", case)



class TrialPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.app = Planning(Path(self.directory.name), None)

    def test_new_numeric_failures_store_no_record_and_normal_save_still_works(self):
        for changes in ({"complete_elapsed_seconds": 1e-308}, {"xp_gain": 10**400},
                        {"scope": {**SCOPE, "level_end": 2**53}}):
            with self.subTest(changes=tuple(changes)), self.assertRaisesRegex(DomainError, "trial_measurement_out_of_range"):
                self.app.handle("POST", "/v1/trials", {**BASE_TRIAL, **changes})
        with connect(self.app.database) as db:
            self.assertEqual(0, db.execute("SELECT count(*) FROM trials").fetchone()[0])
        self.assertEqual("confirmed", self.app.handle("POST", "/v1/trials", BASE_TRIAL)["measurement_status"])

    def test_legacy_numeric_record_is_reclassified_without_changing_its_bytes(self):
        raw = {**BASE_TRIAL, "complete_elapsed_seconds": 1e-308}
        stored = canonical({**raw, "measurement_status": "confirmed", "unknowns": []})
        with connect(self.app.database) as db:
            db.execute("INSERT INTO trials VALUES (?,?)", (raw["trial_id"], stored))
        retried = self.app.handle("POST", "/v1/trials", raw)
        self.assertEqual("uncertain", retried["measurement_status"])
        self.assertIn("trial_measurement_out_of_range", retried["unknowns"])
        good = {**BASE_TRIAL, "trial_id": "good", "map_id": "map-b"}
        self.app.handle("POST", "/v1/trials", good)
        before = self.app.handle("POST", "/v1/routes/compare", {"scope": SCOPE, "candidates": CANDIDATES})
        for _ in range(10):
            self.assertEqual(before, self.app.handle("POST", "/v1/routes/compare",
                                                   {"scope": SCOPE, "candidates": CANDIDATES}))
        self.assertEqual("map-b", before["best_measured_candidate"]["map_id"])
        with connect(self.app.database) as db:
            self.assertEqual(stored, db.execute("SELECT payload FROM trials WHERE id=?", (raw["trial_id"],)).fetchone()[0])
        with self.assertRaises(DomainError) as conflict:
            self.app.handle("POST", "/v1/trials", {**raw, "xp_gain": 101})
        self.assertEqual(409, conflict.exception.status)

    def test_retries_depend_on_inputs_and_concurrent_writes_do_not_duplicate(self):
        stored = canonical({**BASE_TRIAL, "measurement_status": "uncertain", "unknowns": ["old-classification"]})
        with connect(self.app.database) as db:
            db.execute("INSERT INTO trials VALUES (?,?)", (BASE_TRIAL["trial_id"], stored))
        self.assertEqual("confirmed", self.app.handle("POST", "/v1/trials", BASE_TRIAL)["measurement_status"])
        fresh = {**BASE_TRIAL, "trial_id": "concurrent"}
        barrier = threading.Barrier(2)
        def save():
            barrier.wait(timeout=5)
            return self.app.handle("POST", "/v1/trials", fresh)
        with ThreadPoolExecutor(max_workers=2) as workers:
            futures = [workers.submit(save) for _ in range(2)]
            left, right = (future.result(timeout=5) for future in futures)
        self.assertEqual(left, right)
        with connect(self.app.database) as db:
            self.assertEqual(1, db.execute("SELECT count(*) FROM trials WHERE id=?", ("concurrent",)).fetchone()[0])
            self.assertEqual(stored, db.execute("SELECT payload FROM trials WHERE id=?", (BASE_TRIAL["trial_id"],)).fetchone()[0])

    def test_http_numeric_rejection_and_legacy_recovery_leave_service_healthy(self):
        token = secrets.token_urlsafe(32)
        server = LocalServer(self.app, token)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            client = Client(server.url, token)
            for changes in ({"complete_elapsed_seconds": 1e-308}, {"xp_gain": 10**400}):
                with self.subTest(changes=tuple(changes)), self.assertRaises(DomainError) as rejected:
                    client.call("POST", "/v1/trials", {**BASE_TRIAL, **changes})
                self.assertEqual(400, rejected.exception.status)
                self.assertEqual("trial_measurement_out_of_range", rejected.exception.code)
            client.call("POST", "/v1/trials", BASE_TRIAL)
            result = client.call("POST", "/v1/routes/compare", {"scope": SCOPE, "candidates": CANDIDATES})
            self.assertEqual(100, result["routes"][0]["xp_per_minute"])
            self.assertEqual({"service": "planning", "contract_version": 1}, client.call("GET", "/v1/health"))
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())


class SampleTests(unittest.TestCase):
    def sample(self):
        return {"context": PACK["context"], "target_event": "fixture-core-item", "attempt_unit": "run",
                "method": "observed_counts", "coverage": "complete", "version_unchanged": True,
                "attempts": 100, "successes": 10}

    def test_observed_counts_have_defined_scope_and_uncertainty(self):
        result = drop_estimate(self.sample())
        self.assertEqual(.1, result["estimate"])
        self.assertLess(result["interval"][0], .1)
        self.assertGreater(result["interval"][1], .1)
        self.assertEqual(100, result["sample_size"])
        self.assertEqual("run", result["attempt_unit"])

    def test_zero_successes_does_not_prove_zero_probability(self):
        sample = self.sample()
        sample["successes"] = 0
        result = drop_estimate(sample)
        self.assertGreater(result["interval"][1], 0)
        self.assertIsNone(result["expected_attempts_at_observed_rate"])

    def test_weights_missing_outcomes_and_stale_versions_are_rejected(self):
        for key, value, code in (("method", "client_weights", "weights_are_not_probabilities"),
                                 ("coverage", "partial", "unrecorded_attempts_are_not_failures"),
                                 ("version_unchanged", False, "stale_version_sample")):
            with self.subTest(key=key), self.assertRaisesRegex(DomainError, code):
                drop_estimate({**self.sample(), key: value})

    def test_interoperable_count_boundary_stays_exact_and_finite(self):
        maximum = 2**53 - 1
        for successes in (0, 1, maximum - 1, maximum):
            with self.subTest(successes=successes):
                result = drop_estimate({**self.sample(), "attempts": maximum, "successes": successes})
                self.assertEqual(maximum, result["sample_size"])
                self.assertEqual(successes, result["observed_successes"])
                self.assertEqual(result, parse_json(canonical(result)))
                self.assertTrue(all(math.isfinite(x) for x in [result["estimate"], *result["interval"]]))
                self.assertTrue(0 <= result["interval"][0] <= result["interval"][1] <= 1)

    def test_http_rejects_unsafe_counts_without_poisoning_valid_samples(self):
        token = secrets.token_urlsafe(32)
        with tempfile.TemporaryDirectory() as directory:
            server = LocalServer(Planning(Path(directory), None), token)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                client = Client(server.url, token)
                for attempts in (2**53, 10**400):
                    with self.subTest(digits=len(str(attempts))), self.assertRaises(DomainError) as rejected:
                        client.call("POST", "/v1/drop-estimates",
                                    {**self.sample(), "attempts": attempts, "successes": 1})
                    self.assertEqual(400, rejected.exception.status)
                    self.assertEqual("invalid_sample_counts", rejected.exception.code)
                expected = drop_estimate(self.sample())
                self.assertEqual(expected, client.call("POST", "/v1/drop-estimates", self.sample()))
                self.assertEqual({"service": "planning", "contract_version": 1},
                                 client.call("GET", "/v1/health"))
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
                self.assertFalse(worker.is_alive())

    def test_invalid_sample_counts_are_rejected(self):
        for n, k in ((0, 0), (1, 2), (1, -1), (True, 0), (100, True), (100.0, 1), (2**53, 1), (10**400, 1)):
            with self.subTest(n=n, k=k), self.assertRaises(DomainError):
                drop_estimate({**self.sample(), "attempts": n, "successes": k})


if __name__ == "__main__":
    unittest.main()
