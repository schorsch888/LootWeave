"""Independent local API inputs, measurement summaries, and frozen confirmation."""
from __future__ import annotations

import copy
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from contracts import DomainError, canonical, digest
from services.profile.app import Profile
from services.profile.domain import snapshot
from services.profile.live import draft, normalize_sample, observation
from services.profile.live_cache import LiveInputCache, ObservationCache
from transport import Client, LocalServer

SESSION = "synthetic-local-session-" + "x" * 32
CONTEXT = {"game_id": "deskrawl", "edition": "1.0.0i", "game_build": "25690430", "mode": "online",
           "season": "not_applicable", "ruleset_id": "deskrawl-25690430", "content_entitlements": []}


def equipment(identity, container="inventory", slot="weapon"):
    return {"instance_id": identity, "name": "Fixture wand", "template_id": "FixtureWand", "record_kind": "equipment",
            "slot": slot, "container": container, "ownership": "held", "settlement": "settled", "rarity": "Rare",
            "upgrade_level": 2, "required_level": 3, "sockets": 1, "sockets_used": 1, "item_level": 20,
            "affixes": [{"id": "Intelligence", "name": "Intelligence", "value": 12, "unit": "unverified",
                         "roll": {"quality": 0.4, "low": 8, "high": 18}}]}


def run(identity, now, **fields):
    return {"id": identity, "map": "Fixture map", "difficulty": "FixtureDifficulty", "level": 12, "result": "clear",
            "partial": False, "t0": now - 100, "t1": now - 50, "dur": 50, "exp": 100, "gold": 20, "deaths": 0,
            "wave": 8, "waves": 8, "loot": {"Rare": 2},
            "damage": {"dmg": 200, "hits": 4, "crits": 1, "kills": 2, "active": 3, "partial": False,
                       "sources": [{"id": "skill-a", "name": "Fixture skill", "actor": "player", "dmg": 200,
                                    "hits": 4, "crits": 1, "kills": 2}]}, **fields}


def sample_document():
    now = datetime.now(timezone.utc)
    seconds = now.timestamp()
    return {"schema": "lootweave-live/1", "producer_id": "desktop", "captured_at": now.isoformat(),
            "context": copy.deepcopy(CONTEXT), "class_id": "sorcerer",
            "character": {"name": "Synthetic hero", "level": 12, "gold": 42},
            "items": [equipment("equipped", "equipment"), equipment("candidate"), equipment("ring", "storage", "ring")],
            "equipped_slots": ["weapon", "ring1", "ring2"],
            "coverage": {name: "partial" for name in ("equipment", "inventory", "storage", "carriage")},
            "abilities": [{"id": "FixtureAbility", "rank": 2, "name": "Fixture skill", "role": "basic_attack"}],
            "talents": [{"id": "FixtureTalent", "rank": 3, "name": "Fixture talent", "max": 5, "description": "合成天赋说明"}],
            "overview": {"character": {"xp": 350, "hp": {"current": 180, "max": 200}, "mana": {"current": 80, "max": 100},
                                       "area": "Combat", "map": {"key": "FixtureMap", "label": "Fixture map"}},
                         "stats": {"final": {"Intelligence": 32}, "base": {"Intelligence": 12}},
                         "panel": {"dps": 999777, "toughness": 456, "recovery": 78, "formula": "Fictional estimate"},
                         "materials": [{"id": "FixtureIron", "name": "Fixture iron", "amount": 5},
                                       {"id": "FixtureZero", "name": "Fixture empty material", "amount": 0},
                                       {"id": "FixtureUnknown", "name": "Fixture unknown material", "amount": None}],
                         "capacity": {"inventory": {"used": 1, "capacity": 100, "level": "ok"},
                                      "carriage": {"used": 11, "capacity": 12, "fullness_used": 12, "level": "full"}},
                         "carriage": {"active_companion": "FixtureCompanion", "base_capacity": 10, "extra_capacity": 2,
                                      "game_label": "11/12", "game_label_match": True, "pickup_rarities": ["Rare"],
                                      "autofill_inventory": True, "in_combat": True},
                         "in_flight_count": 1, "ground": [{"name": "Fixture ground wand", "rarity": "Rare", "registered": False}],
                         "run": {"in_run": True, "map": "Fixture map", "difficulty": "FixtureDifficulty", "waves_total": 8,
                                 "wave_index": 2, "planned_items": 10, "picked_unminted": 1, "committed": False},
                         "forecast": {"map": "Fixture map", "waves": [{"wave": 4, "items": [{"name": "Fixture upcoming wand", "rarity": "Rare", "status": "upcoming"}]}]},
                         "chests": [{"name": "Fixture unopened chest", "contents": [{"name": "Fixture sealed wand", "rarity": "Rare"}]}],
                         "town_checklist": {"store": [{"name": "Fixture town ring", "container": "inventory"}]},
                         "features": {name: "partial" for name in ("character", "final_stats", "panel", "carriage", "run_progress", "runplan_forecast", "chest_preview")}},
            "report_coverage": {name: "complete" for name in ("runs", "combat", "lineage", "loadouts", "status")},
            "reports": {"runs": {"records": [run("one", seconds), run("two", seconds, dur=100, exp=100, gold=40),
                                             run("partial", seconds, partial=True, exp=9000)]},
                        "combat": {"coverage_started_at": seconds-120, "session_started_at": seconds-120,
                                   "events": [{"at": seconds-offset, "source_id": "FixtureSkill", "source_name": "Fixture skill", "actor": "player",
                                               "damage": amount, "hits": 1, "crits": 0, "kills": 1}
                                              for offset, amount in ((5, 100), (20, 50), (59, 20), (61, 30))]},
                        "lineage": {"draws": [{"name": "Fixture drawn wand", "rarity": "Legendary", "ancient": True, "black_mist": None,
                                               "price": 10, "how": "manual", "piece": "weapon", "time": seconds-10},
                                              {"name": "Fixture drawn ring", "rarity": "Rare", "ancient": False, "black_mist": False,
                                               "price": 20, "how": "auto", "piece": "ring", "time": seconds-5}],
                                    "finds": [{"name": "Fixture notable wand", "rarity": "Legendary", "market": True, "time": seconds-2}]},
                        "loadouts": {"slots": [{"slot": 1, "name": "Fixture boss build", "empty": False, "worn": False,
                                                "abilities": [{"role": "basic_attack", "key": "FixtureSkill", "name": "Fixture skill"}],
                                                "gear": [{"slot": "weapon", "key": "FixtureWand", "name": "Fixture saved wand", "rarity": "Rare"}],
                                                "missing": [{"slot": "weapon", "name": "Fixture saved wand", "reason": "storage"}]}]},
                        "status": {"producer_version": "1.0", "collection_coverage": {"equipment": "partial"},
                                   "events": [{"kind": "sample", "action": "capture", "ok": True}],
                                   "catalogs": {"maps": [{"key": "FixtureMap", "name": "Fixture map", "entry": [{"item": "FixtureTicket", "amount": 2}]}],
                                                "potions": [{"key": "FixturePotion", "name": "Fixture potion", "recipe": {"quantity": 1, "ingredients": [{"key": "FixtureIron", "amount": 2}]}}],
                                                "affix_pools": {"weapon": ["Intelligence"]}, "gem_kinds": ["FixtureGem"], "rune_rarities": ["Rare"]}}},
            "private_path": "synthetic-private-machine", "token": "synthetic-source-credential"}


class LiveNormalizationTests(unittest.TestCase):
    def preview(self, value=None):
        return observation(normalize_sample(value or sample_document()), "live-fixture", CONTEXT, "sorcerer")

    def assert_code(self, code, action):
        with self.assertRaises(DomainError) as failure:
            action()
        self.assertEqual(code, failure.exception.code)

    def test_own_schema_and_private_fields(self):
        value = sample_document()
        value["context"]["private_path"] = "synthetic-private-context"
        value["reports"]["status"]["events"][0]["token"] = "synthetic-event-token"
        result = self.preview(value)
        encoded = canonical(result)
        for private in ("synthetic-private-machine", "synthetic-private-context", "synthetic-source-credential", "synthetic-event-token"):
            self.assertNotIn(private, encoded)
        self.assertEqual("lootweave-live/1", result["source"]["schema"])
        self.assertEqual("live_api", result["method"])
        self.assertEqual("unconfirmed", result["state"])
        self.assert_code("live_schema_unsupported", lambda: normalize_sample({**value, "schema": "unsupported-sample/1"}))

    def test_draft_keeps_owned_records_and_known_resources_only(self):
        result = self.preview()
        facts = snapshot(draft(result, result["items"][1]["id"]))
        self.assertEqual("live_api_confirmation", facts["evidence"][0]["kind"])
        self.assertEqual(12, facts["candidate_item"]["affixes"][0]["value"])
        self.assertEqual([], facts["observed_panel"])
        self.assertEqual([], facts["candidate_item"]["effects"])
        self.assertEqual("partial", facts["inventory_coverage"])
        self.assertEqual({"gold": 42, "live.FixtureIron": 5, "live.FixtureZero": 0},
                         {row["resource_id"]: row["amount"] for row in facts["owned_resources"]["balances"]})
        self.assertNotIn("upcoming", canonical(facts))
        self.assertIn("embedded_items_not_observed", facts["candidate_item"]["unrevealed_properties"])

    def test_preview_items_and_unsettled_items_cannot_be_candidates(self):
        value = sample_document()
        value["items"].append({**equipment("future"), "ownership": "preview"})
        result = self.preview(value)
        self.assertEqual(3, len(result["items"]))
        self.assert_code("live_candidate_required", lambda: draft(result, result["items"][0]["id"]))
        for settlement in ("pending", "unknown", "not_required"):
            value["items"][1]["settlement"] = settlement
            result = self.preview(value)
            self.assertTrue(result["items"][1]["blocked"])
        value["context"]["mode"] = "local"
        value["items"][1]["settlement"] = "not_required"
        normalized = normalize_sample(value)
        self.assertEqual([], normalized["items"][1]["blocked"])

    def test_ring_target_and_duplicate_instances(self):
        result = self.preview()
        self.assert_code("live_ring_slot_required", lambda: draft(result, result["items"][2]["id"]))
        self.assertEqual("ring2", draft(result, result["items"][2]["id"], "ring2")["candidate_item"]["slot"])
        value = sample_document()
        value["items"][2]["instance_id"] = "candidate"
        result = self.preview(value)
        self.assertTrue(all("duplicate_instance" in row["blocked"] for row in result["items"][1:]))

    def test_duplicate_slots_and_unknown_affixes_remain_unread(self):
        value = sample_document()
        value["items"].append(equipment("second-equipped", "equipment"))
        result = self.preview(value)
        self.assertNotIn("weapon", result["equipped_slots"])
        value = sample_document()
        del value["items"][1]["affixes"]
        self.assertIn("affixes_unavailable", self.preview(value)["items"][1]["blocked"])

    def test_context_class_and_source_time_bind(self):
        normalized = normalize_sample(sample_document())
        self.assert_code("live_context_mismatch", lambda: observation(normalized, "bad", {**CONTEXT, "mode": "local"}, "sorcerer"))
        self.assert_code("live_class_mismatch", lambda: observation(normalized, "bad", CONTEXT, "hunter"))
        for delta in (-121, 31):
            value = sample_document()
            value["captured_at"] = (datetime.now(timezone.utc)+timedelta(seconds=delta)).isoformat()
            self.assert_code("live_source_stale", lambda: normalize_sample(value))

    def test_content_hash_ignores_source_clock_but_tracks_observed_changes(self):
        value = sample_document()
        value.pop("reports"); value.pop("report_coverage")
        first = self.preview(value)
        value["captured_at"] = datetime.now(timezone.utc).isoformat()
        second = self.preview(value)
        self.assertEqual(first["source"]["content_hash"], second["source"]["content_hash"])
        value["overview"]["character"]["hp"]["current"] = 179
        self.assertNotEqual(first["source"]["content_hash"], self.preview(value)["source"]["content_hash"])

    def test_damage_windows_use_full_time_and_preserve_missing_windows(self):
        result = self.preview()["telemetry"]["combat"]["data"]
        self.assertEqual(10, result["live"]["dps10"])
        self.assertAlmostEqual(170/60, result["live"]["dps60"])
        self.assertEqual(200, result["session"]["dmg"])
        self.assertEqual(4, result["session"]["hits"])
        value = sample_document(); combat = value["reports"]["combat"]
        combat["coverage_started_at"] = None
        self.assertIsNone(self.preview(value)["telemetry"]["combat"]["data"]["live"]["dps10"])
        combat["events"] = []
        result = self.preview(value)["telemetry"]["combat"]["data"]
        self.assertTrue(result["session"]["partial"])

    def test_run_rates_weight_by_duration_and_exclude_partial_records(self):
        result = self.preview()["telemetry"]["runs"]["data"]
        self.assertEqual(3, result["total"])
        self.assertEqual(2, result["rates"]["runs"])
        self.assertAlmostEqual(200/150, result["rates"]["exp_s"])
        self.assertEqual(150, result["window_maps"][0]["dur"])
        self.assertEqual(2, result["window_maps"][0]["runs"])
        self.assertNotIn("char", canonical(result))

    def test_lineage_uses_observed_frequencies_without_assumed_odds(self):
        data = self.preview()["telemetry"]["lineage"]["data"]
        self.assertEqual(2, data["gamble"]["all"]["draws"])
        self.assertEqual(30, data["gamble"]["all"]["shards"])
        self.assertEqual(0.5, data["gamble"]["all"]["top"]["rate"])
        self.assertIsNone(data["gamble"]["all"]["black_mist"]["rate"])
        self.assertEqual(1, data["gamble"]["manual"]["draws"])
        self.assertEqual(1, len(data["market"]))
        self.assertNotIn("odds", data)
        self.assertNotIn("verdict", data)

    def test_missing_reports_and_counts_remain_unknown(self):
        value = sample_document(); value.pop("reports"); value.pop("report_coverage")
        value.pop("coverage")
        result = self.preview(value)
        self.assertTrue(all(result["telemetry"][name]["data"] is None for name in ("runs", "combat", "lineage", "loadouts", "status")))
        self.assertIsNone(result["overview"]["statistics"]["total_deaths"])
        self.assertTrue(all(state == "unavailable" for state in result["coverage"].values()))

    def test_counts_fields_lists_and_forecast_have_bounds(self):
        for mutate in (lambda value: value["items"][1].update(sockets=-1),
                       lambda value: value["items"][1].update(sockets_used=2),
                       lambda value: value["reports"]["combat"]["events"][0].update(damage=-1),
                       lambda value: value["reports"]["runs"].update(records=[{**value["reports"]["runs"]["records"][0], "dur": 1e-320}]),
                       lambda value: value["reports"]["runs"]["records"].append(value["reports"]["runs"]["records"][0]),
                       lambda value: value["reports"]["loadouts"]["slots"][0].update(slot=6)):
            value = sample_document(); mutate(value)
            self.assert_code("live_sample_invalid", lambda: normalize_sample(value))
        value = sample_document(); value["overview"]["materials"] *= 2
        self.assert_code("live_material_conflict", lambda: normalize_sample(value))
        value = sample_document(); value["items"] *= 701
        self.assert_code("live_sample_too_large", lambda: normalize_sample(value))

    def test_missing_item_flags_and_loadout_slots_are_not_known_empty(self):
        value = sample_document()
        preview = self.preview(value)
        self.assertIsNone(preview["items"][1]["locked"])
        self.assertIsNone(preview["items"][1]["ancient"])
        self.assertIsNone(preview["items"][1]["black_mist"])
        facts = snapshot(draft(preview, preview["items"][1]["id"]))
        self.assertIn("item_flags_not_observed", facts["candidate_item"]["unknowns"])
        slots = preview["telemetry"]["loadouts"]["data"]["slots"]
        self.assertEqual(5, len(slots))
        self.assertIsNone(slots[1]["empty"])
        self.assertIsNone(slots[1]["worn"])
        value["items"][1].update(locked=False, ancient=False, black_mist=False)
        preview = self.preview(value)
        facts = snapshot(draft(preview, preview["items"][1]["id"]))
        self.assertIs(preview["items"][1]["locked"], False)
        self.assertNotIn("item_flags_not_observed", facts["candidate_item"]["unknowns"])

    def test_own_contract_can_carry_sockets_paragon_and_other_build_sources(self):
        value = sample_document()
        value["items"][1]["embedded_items"] = [{"id": "FixtureGem", "name": "Fixture gem", "rank": 1}]
        value["paragon"] = [{"id": "FixtureParagon", "rank": 4}]
        value["runes"] = [{"id": "FixtureRune", "set_id": "FixtureSet"}]
        value["companions"] = [{"id": "FixtureCompanion", "companion_id": "FixtureCompanion", "actor": "companion", "level": 12}]
        value["temporary_effects"] = [{"id": "FixtureBuff"}]
        value["observed_panel"] = [{"stat": "Intelligence", "value": 32, "unit": "points", "source_ids": []}]
        preview = self.preview(value); facts = snapshot(draft(preview, preview["items"][1]["id"]))
        self.assertEqual("live.FixtureGem", facts["candidate_item"]["embedded_items"][0]["id"])
        self.assertNotIn("embedded_items_not_observed", facts["candidate_item"]["unrevealed_properties"])
        self.assertEqual(4, facts["paragon"][0]["rank"])
        self.assertEqual("live.FixtureCompanion", facts["companions"][0]["companion_id"])
        self.assertEqual(32, facts["observed_panel"][0]["value"])

    def test_partial_event_coverage_never_produces_a_complete_window_dps(self):
        value = sample_document(); value["report_coverage"]["combat"] = "partial"
        result = self.preview(value)["telemetry"]["combat"]
        self.assertEqual("partial", result["state"])
        self.assertIsNone(result["data"]["live"]["dps60"])


class LiveHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.app = Profile(Path(self.temp.name)); self.server = LocalServer(self.app, SESSION)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True); thread.start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.client = Client(self.server.url, SESSION)
        self.value = sample_document()

    def publish(self, value=None):
        return self.client.call("POST", "/v1/live/samples", value or self.value)

    def read(self, identity="read", previous=None, **extra):
        return self.client.call("POST", "/v1/imports/live/read", {
            "observation_id": identity, "producer_id": "desktop", "context": CONTEXT,
            "class_id": "sorcerer", "scope_confirmed": True,
            **({"previous_content_hash": previous} if previous else {}), **extra})

    def test_ingest_read_and_poll_do_not_save_facts_or_observations(self):
        self.publish(); first = self.read()
        reply = self.read("poll", first["source"]["content_hash"])
        self.assertTrue(reply["unchanged"]); self.assertNotIn("items", reply)
        self.assertNotIn("telemetry", reply)
        with self.app.connect() as db:
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM observations").fetchone()[0])
            self.assertEqual(0, db.execute("SELECT COUNT(*) FROM revisions").fetchone()[0])
        self.assertEqual("desktop", self.client.call("GET", "/v1/live/sources")["sources"][0]["producer_id"])

    def test_draft_and_confirmation_freeze_source_without_network_clients(self):
        self.publish(); first = self.read()
        imported = self.client.call("POST", "/v1/imports/live/draft", {"observation_id": "read", "candidate_id": first["items"][1]["id"]})
        self.value["captured_at"] = datetime.now(timezone.utc).isoformat()
        self.value["items"][1]["affixes"][0]["value"] = 99
        self.publish(); self.read("new")
        self.assertEqual(12, imported["facts"]["candidate_item"]["affixes"][0]["value"])
        body = {"request_id": "confirm-live", "profile_id": "local-profile", "observation_id": "read", "expected_revision": 0,
                "player_confirmed": True, "facts": imported["facts"]}
        result = self.client.call("POST", "/v1/confirmations", body)
        self.assertEqual("verified", result["observation_time_status"])
        self.assertEqual(result, self.client.call("POST", "/v1/confirmations", body))
        self.assertEqual(result, self.client.call("GET", "/v1/profiles/local-profile/revisions/1"))
        with self.app.connect() as db:
            self.assertNotIn("synthetic-source-credential", db.execute("SELECT payload FROM observations").fetchone()[0])

    def test_confirmation_binds_context_class_and_time(self):
        self.publish(); value = self.read()
        facts = self.client.call("POST", "/v1/imports/live/draft", {"observation_id": "read", "candidate_id": value["items"][1]["id"]})["facts"]
        for mutate, code in ((lambda value: value["context"].update(game_build="other"), "observation_context_conflict"),
                             (lambda value: value.update(class_id="hunter"), "observation_class_conflict"),
                             (lambda value: value.update(captured_at="2026-01-01T00:00:00Z"), "observation_time_conflict")):
            changed = copy.deepcopy(facts); mutate(changed)
            with self.assertRaises(DomainError) as failure:
                self.client.call("POST", "/v1/confirmations", {"request_id": "bad-confirm", "profile_id": "local-profile", "observation_id": "read",
                    "expected_revision": 0, "player_confirmed": True, "facts": changed})
            self.assertEqual(code, failure.exception.code)

    def test_removed_external_endpoints_and_connection_fields_are_rejected(self):
        self.publish()
        for path in ("/v1/imports/retired-provider/read", "/v1/imports/retired-provider/preview", "/control/combat"):
            with self.assertRaises(DomainError) as error:
                self.client.call("POST", path, {})
            self.assertEqual("invalid_api_path" if path.startswith("/control/") else "not_found", error.exception.code)
        with self.assertRaises(DomainError) as error:
            self.read(port=8765, token="a"*64)
        self.assertEqual("live_request_invalid", error.exception.code)

    def test_missing_stale_and_mismatched_sources_fail_without_revisions(self):
        with self.assertRaises(DomainError) as error:
            self.read()
        self.assertEqual("live_source_missing", error.exception.code)
        self.publish()
        for extra, code in (({"class_id": "hunter"}, "live_class_mismatch"),
                            ({"context": {**CONTEXT, "mode": "local"}}, "live_context_mismatch"),
                            ({"scope_confirmed": False}, "live_scope_confirmation_required")):
            with self.assertRaises(DomainError) as error:
                self.read(**extra)
            self.assertEqual(code, error.exception.code)
        sampled = datetime.fromisoformat(self.value["captured_at"])
        with patch("services.profile.live.datetime") as clock:
            clock.now.return_value = sampled + timedelta(seconds=121)
            with self.assertRaises(DomainError) as error:
                self.read()
        self.assertEqual("live_source_stale", error.exception.code)

    def test_samples_are_ordered_and_observation_ids_are_immutable(self):
        self.publish(); first = self.read()
        changed = copy.deepcopy(self.value); changed["character"]["gold"] = 43
        with self.assertRaises(DomainError) as error:
            self.publish(changed)
        self.assertEqual("live_sample_time_conflict", error.exception.code)
        changed["captured_at"] = (datetime.fromisoformat(self.value["captured_at"])-timedelta(seconds=1)).isoformat()
        with self.assertRaises(DomainError) as error:
            self.publish(changed)
        self.assertEqual("live_sample_out_of_order", error.exception.code)
        changed["captured_at"] = datetime.now(timezone.utc).isoformat(); self.publish(changed)
        with self.assertRaises(DomainError) as error:
            self.read()
        self.assertEqual("observation_id_conflict", error.exception.code)
        self.assertEqual(first, self.app.live_reads.get("read"))

    def test_live_samples_require_the_owning_session_credential(self):
        with self.assertRaises(DomainError) as error:
            Client(self.server.url, "wrong-session").call("POST", "/v1/live/samples", self.value)
        self.assertEqual("unauthorized", error.exception.code)
        self.assertEqual([], self.app.live_inputs.sources())


class LiveCacheTests(unittest.TestCase):
    def test_cache_copy_memory_and_expiry_bounds(self):
        cache = ObservationCache(max_entries=2, max_bytes=100, ttl=10)
        cache.put("one", canonical({"item": "甲"})); cache.put("two", canonical({"item": "乙"})); cache.put("three", canonical({"item": "丙"}))
        self.assertIsNone(cache.get("one"))
        changed = cache.get("two"); changed["item"] = "changed"
        self.assertEqual("乙", cache.get("two")["item"])
        self.assertLessEqual(cache.bytes, 100)
        with self.assertRaises(DomainError): cache.put("big", canonical({"value": "x"*101}))
        with patch("services.profile.live_cache.monotonic", return_value=0):
            cache = LiveInputCache(ttl=10); cache.publish("one", {"captured_at": "2026-10-05T00:00:00.000Z"})
        with patch("services.profile.live_cache.monotonic", return_value=11):
            self.assertIsNone(cache.get("one")); self.assertEqual([], cache.sources())


if __name__ == "__main__":
    unittest.main()
