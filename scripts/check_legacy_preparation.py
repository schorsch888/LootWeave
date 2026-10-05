"""Compare current 0.1.7 preparation results with the pinned main baseline."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

BASELINE_REV = "075a033415478d0b51193314f50cf9c951ec6694"
EMITTER = r'''
import copy, json
from contracts import digest
from tests.test_preparation import prepared_case, run_case, skill_quote

def cases():
    base_facts, base_purpose = prepared_case()
    rows = []
    def add(name, mutate=lambda facts, purpose: None):
        facts, purpose = copy.deepcopy(base_facts), copy.deepcopy(base_purpose)
        mutate(facts, purpose)
        result = run_case(facts, purpose, version="0.1.7")
        rows.append({"case": name, "result": result, "result_hash": digest(result)})
    add("combined_skill_equipment_cost")
    add("insufficient_resources", lambda f, p: f["owned_resources"]["balances"][0].update(amount=8))
    add("unknown_resources", lambda f, p: f.pop("owned_resources"))
    add("unknown_cost", lambda f, p: f["preparation_options"][0].update(costs=None))
    add("locked_unlock", lambda f, p: f["preparation_options"][0]["requirements"].update(unlock_state="locked"))
    def stale_skill(f, p):
        quote = skill_quote(f, f["skills"][0]["id"], rank=5, option_id="improve-current", cost=0)
        f["preparation_options"].append(quote)
        p["future_builds"][0]["preparation_options"].append(quote["id"])
        f["skills"][0]["rank"] += 1
    add("stale_skill_input", stale_skill)
    add("missing_skill_removal_quote", lambda f, p: p["future_builds"][0]["skills"].remove(f["skills"][0]["id"]))
    add("unknown_condition", lambda f, p: p["future_builds"][0]["conditions"].update(hero_cast="unknown"))
    return rows

print(json.dumps({"rows": cases()}, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
'''

def fail(message):
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-dir", required=True, type=Path)
    args = parser.parse_args()
    current = Path(__file__).resolve().parents[1]
    baseline = args.baseline_dir.resolve()
    if baseline == current:
        fail("baseline directory must differ from current root")
    if not (baseline / ".git").exists() or not (baseline / "tests" / "test_preparation.py").is_file():
        fail("baseline git metadata or preparation fixtures missing")
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=baseline,
                              capture_output=True, text=True, timeout=30)
    if revision.returncode or revision.stdout.strip() != BASELINE_REV:
        fail("baseline revision mismatch")
    outputs = []
    for root in (current, baseline):
        try:
            completed = subprocess.run([sys.executable, "-c", EMITTER], cwd=root,
                                       capture_output=True, text=True, timeout=30)
        except subprocess.TimeoutExpired:
            fail("case emitter timed out")
        if completed.returncode:
            fail("case emitter failed")
        try:
            payload = json.loads(completed.stdout)
        except (ValueError, TypeError):
            fail("case emitter returned invalid JSON")
        if not isinstance(payload, dict) or set(payload) != {"rows"} or not isinstance(payload["rows"], list):
            fail("case emitter output shape mismatch")
        outputs.append(payload["rows"])
    now, old = outputs
    if len(now) < 8 or len(now) != len(old):
        fail("case count mismatch")
    if [row.get("case") for row in now] != [row.get("case") for row in old]:
        fail("case identities differ")
    if any("result" not in row or "result_hash" not in row for row in now + old):
        fail("result fields missing")
    if any(a["result"] != b["result"] or a["result_hash"] != b["result_hash"]
           for a, b in zip(now, old)):
        fail("historical results differ")
    print(f"PASS: {len(now)} historical preparation cases; results and hashes match")

if __name__ == "__main__":
    main()
