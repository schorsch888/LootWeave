"""Validate packaged preparation persistence through the Rust headless API.

Uses fictional inputs only; this does not validate a visible GUI, real-game
mechanics, or clean-machine installer behavior."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from check_desktop import CheckFailed, Desktop, expect
from contracts import DomainError, digest
from test_preparation import prepared_case
from test_future_builds import full_case


def require(condition, code):
    expect(condition, code)


def future_report(result):
    reports = result.get("future_preparation")
    require(isinstance(reports, list) and len(reports) == 1, "preparation_report_missing")
    return reports[0]


def resource(report):
    rows = report.get("resources", [])
    require(len(rows) == 1 and rows[0].get("resource_id") == "fixture-shard",
            "preparation_resource_row_invalid")
    return rows[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--resources", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Requires the Windows native desktop host.")
    executable, resources, report_path = args.executable.resolve(), args.resources.resolve(), args.report.resolve()
    if not executable.is_file() or not (resources / "bundle-manifest.json").is_file():
        parser.error("Packaged executable or resources are unavailable.")

    started = time.perf_counter()
    checks = []
    fixture_hashes = {}
    app = None
    stage = "temporary_data"
    failure_code = None
    with tempfile.TemporaryDirectory(prefix="lootweave-preparation-") as temporary:
        data = Path(temporary) / "data"
        data.mkdir()
        try:
            stage = "fixture_inputs"
            facts, purpose = prepared_case()
            fixture_path = ROOT / "fixtures" / "demo.json"
            pack_path = ROOT / "knowledge-packs" / "synthetic-leveling-1.0.0.json"
            fixture_hashes = {
                "demo_fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
                "prepared_facts": digest(facts),
                "synthetic_pack_sha256": hashlib.sha256(pack_path.read_bytes()).hexdigest(),
            }

            stage = "host_start"
            app = Desktop(executable, resources, data)
            for service in ("profile", "knowledge", "evaluation"):
                app.ensure(service)
            health = app.call("GET", "/api/evaluation/health")
            version = health.get("evaluator_version")
            require(version == "0.1.8", "packaged_evaluator_version_mismatch")
            checks.append("packaged_evaluator_0_1_8")

            stage = "profile_observation_and_confirmation"
            app.call("POST", "/api/profile/observations", {
                "observation_id": "demo-text", "method": "text",
                "raw_text": "Fictional preparation fixture",
            })
            profile = app.call("POST", "/api/profile/confirmations", {
                "request_id": "preparation-confirm", "profile_id": "preparation-fixture",
                "observation_id": "demo-text", "expected_revision": 0,
                "player_confirmed": True, "facts": facts,
            })
            require(profile["revision"] == 1 and profile["facts_hash"] == digest(facts),
                    "confirmed_preparation_profile_invalid")
            packs = app.call("GET", "/api/knowledge/packs")["packs"]
            matches = [item for item in packs if item.get("execution_policy") == "synthetic_only"
                       and item.get("context") == facts["context"]
                       and item.get("class_id") == facts["class_id"]
                       and item.get("scenario") == purpose["scenario"]]
            require(len(matches) == 1, "synthetic_fixture_pack_not_unique")
            pack = matches[0]
            fixture_hashes["pack_hash"] = pack["pack_hash"]
            base_body = {
                "profile_id": "preparation-fixture", "profile_revision": profile["revision"],
                "pack_id": pack["pack_id"], "pack_version": pack["version"],
                "pack_hash": pack["pack_hash"], "intent": purpose,
            }

            stage = "feasible_projection_and_idempotency"
            base_request = {**base_body, "request_id": "preparation-budget-12"}
            feasible = app.call("POST", "/api/evaluation/evaluations", base_request)
            prep = future_report(feasible)
            row = resource(prep)
            require(prep.get("status") == "feasible" and row.get("cost") == 12
                    and row.get("available") == 12 and row.get("budget_limit") == 12
                    and row.get("missing") == 0, "preparation_feasible_budget_12_invalid")
            require(any(skill.get("id") == "fixture-fire-bolt" and skill.get("rank") == 3
                        for skill in prep.get("skill_allocations", [])), "projected_fire_bolt_rank_invalid")
            equipment = [option.get("projected_result") for option in prep.get("options", [])
                         if option.get("kind") == "equipment"]
            require(len(equipment) == 1 and equipment[0].get("record_kind") == "projected_item",
                    "projected_equipment_missing")
            require(feasible.get("pin", {}).get("facts_hash") == digest(facts), "projection_changed_fact_pin")
            current_item = facts["candidate_item"]
            duplicate = app.call("POST", "/api/evaluation/evaluations", base_request)
            require(duplicate == feasible, "evaluation_idempotency_mismatch")
            current_profile = app.call("GET", "/api/profile/profiles/preparation-fixture/revisions/1")
            require(current_profile["facts_hash"] == digest(facts)
                    and current_profile["facts"]["candidate_item"] == current_item,
                    "projection_overwrote_current_facts_or_equipment")
            checks.extend(("prepared_feasible_projection_and_immutable_profile", "evaluation_idempotency"))

            stage = "budget_limit_10"
            low_purpose = copy.deepcopy(purpose)
            low_purpose["budget"]["resource_limits"][0]["amount"] = 10
            low_request = {**base_body, "request_id": "preparation-budget-10", "intent": low_purpose}
            low = app.call("POST", "/api/evaluation/evaluations", low_request)
            low_report = future_report(low)
            low_row = resource(low_report)
            require(low_report.get("status") == "infeasible" and low_row.get("budget_excess") == 2
                    and not any(reason.get("kind") == "future_use" for reason in low.get("reasons", [])),
                    "preparation_budget_10_invalid")
            checks.append("budget_excess_blocks_future_use")

            unknown_facts = copy.deepcopy(facts)
            unknown_facts.pop("owned_resources", None)
            stage = "missing_owned_resources_revision"
            unknown_profile = app.call("POST", "/api/profile/confirmations", {
                "request_id": "preparation-unknown-confirm", "profile_id": "preparation-fixture",
                "observation_id": "demo-text", "expected_revision": 1,
                "player_confirmed": True, "facts": unknown_facts,
            })
            unknown_body = {**base_body, "profile_revision": unknown_profile["revision"],
                            "request_id": "preparation-resources-unknown"}
            unknown = app.call("POST", "/api/evaluation/evaluations", unknown_body)
            unknown_report = future_report(unknown)
            unknown_row = resource(unknown_report)
            require(unknown_report.get("status") == "unknown" and unknown_row.get("available") is None
                    and unknown_row.get("missing") is None
                    and not any(reason.get("kind") == "future_use" for reason in unknown.get("reasons", [])),
                    "missing_owned_resources_misreported")
            require(unknown.get("pin", {}).get("facts_hash") == digest(unknown_facts),
                    "unknown_revision_facts_changed")
            checks.append("omitted_owned_resources_remain_unknown")

            stage = "complete_future_profile_and_projection"
            full_facts, full_purpose = full_case()
            full_profile = app.call("POST", "/api/profile/confirmations", {
                "request_id": "full-future-confirm", "profile_id": "full-future-fixture",
                "observation_id": "demo-text", "expected_revision": 0,
                "player_confirmed": True, "facts": full_facts,
            })
            full_result = app.call("POST", "/api/evaluation/evaluations", {
                **base_body, "request_id": "preparation-full-future", "profile_id": "full-future-fixture",
                "profile_revision": full_profile["revision"], "intent": full_purpose,
            })
            full_report = future_report(full_result)
            require(full_report["status"] == "feasible" and resource(full_report)["cost"] == 24,
                    "complete_future_quote_costs_invalid")
            require(full_report["projection_kind"] == "future_plan", "complete_future_projection_kind_missing")
            require(full_report["build_sources"]["talents"] == [] and full_report["build_sources"]["paragon"] == []
                    and len(full_report["build_sources"]["runes"]) == 1, "complete_future_sources_not_applied")
            full_comparison = full_report["comparison"]
            require(full_comparison["status"] == "mechanism_loss"
                    and {"resource_efficiency", "survival", "frost_cycle"}.issubset(full_comparison["lost_capabilities"])
                    and "survival" in full_comparison["missing_requirements"], "complete_future_dependency_loss_hidden")
            require({"fire_focus", "temporary_focus"}.issubset(full_comparison["gained_capabilities"]),
                    "complete_future_qualified_gains_missing")
            actual_full = app.call("GET", "/api/profile/profiles/full-future-fixture/revisions/1")
            require(actual_full["facts_hash"] == digest(full_facts) and actual_full["facts"] == full_facts,
                    "complete_future_projection_overwrote_actual_profile")
            checks.append("all_six_future_source_groups_and_costs_preserve_actual_facts")

            stage = "first_run_replays"
            results = {
                "preparation-budget-12": feasible,
                "preparation-budget-10": low,
                "preparation-resources-unknown": unknown,
                "preparation-full-future": full_result,
            }
            for evaluation_id, expected in results.items():
                for _ in range(10):
                    replay = app.call("POST", f"/api/evaluation/evaluations/{evaluation_id}/replay", {})
                    require(replay.get("identical") is True and replay.get("result") == expected,
                            "evaluation_replay_mismatch")
            checks.append("all_history_replays_10_times")

            stage = "host_restart"
            app.stop()
            require(app.process.returncode == 0, "first_host_exit_failed")
            app = None
            app = Desktop(executable, resources, data)
            for service in ("profile", "evaluation"):
                app.ensure(service)
            reloaded = app.call("GET", "/api/profile/profiles/preparation-fixture/revisions/2")
            require(reloaded["facts_hash"] == digest(unknown_facts), "profile_restart_read_mismatch")
            full_reloaded = app.call("GET", "/api/profile/profiles/full-future-fixture/revisions/1")
            require(full_reloaded["facts"] == full_facts, "complete_future_profile_restart_mismatch")
            require(any(option["kind"] == "rune" and option["result"] is None
                        for option in full_reloaded["facts"]["preparation_options"]), "nullable_quote_restart_mismatch")
            for evaluation_id, expected in results.items():
                saved = app.call("GET", f"/api/evaluation/evaluations/{evaluation_id}")
                require(saved == expected, "evaluation_restart_read_mismatch")
                for _ in range(10):
                    replay = app.call("POST", f"/api/evaluation/evaluations/{evaluation_id}/replay", {})
                    require(replay.get("identical") is True and replay.get("result") == expected,
                            "restart_replay_mismatch")
            checks.extend(("profile_and_evaluations_survive_restart", "restart_replays_10_times_each"))
            app.stop()
            require(app.process.returncode == 0, "final_host_exit_failed")
            app = None
        except (CheckFailed, DomainError) as error:
            failure_code = str(error) if isinstance(error, CheckFailed) else error.code
            checks.append("failure:" + stage)
            if app is not None:
                app.stop()
                app = None
        except HTTPError:
            failure_code = getattr(app, "last_error", {}).get("code", "http_error")
            checks.append("failure:" + stage)
            if app is not None:
                app.stop()
                app = None
        except Exception:
            failure_code = "unexpected_error"
            checks.append("failure:" + stage)
            if app is not None:
                app.stop()
                app = None

    report = {
        "passed": failure_code is None,
        "scope": "Windows Rust headless host and frozen workers with fictional preparation facts.",
        "evaluator_version": "0.1.8",
        "checks": checks,
        "check_count": len(checks),
        "fixture_hashes": fixture_hashes,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
    }
    if failure_code is not None:
        report["failure_stage"] = stage
        report["failure_code"] = failure_code
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "check_count": len(checks),
                      "elapsed_seconds": report["elapsed_seconds"],
                      **({"failure_stage": stage, "failure_code": failure_code}
                         if failure_code is not None else {})}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as error:
        print(json.dumps({"passed": False, "failure_type": type(error).__name__}))
        raise SystemExit(1) from None
