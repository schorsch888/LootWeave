// Direct ConfirmSnapshot rendering/handler checks with fixture hooks and API responses.
// These checks do not cover React scheduling, native IPC, desktop input, or real-game acceptance.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { createServer } from "../frontend/node_modules/vite/dist/node/index.js";
import { renderToStaticMarkup } from "../frontend/node_modules/react-dom/server.node.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const sourcePath = "frontend/src/features/confirm-snapshot/index.tsx";
const apiPath = "frontend/src/shared/api/index.ts";
const source = resolve(root, sourcePath).replaceAll("\\", "/");
const reportIndex = process.argv.indexOf("--report");
const reportPath = reportIndex >= 0 ? process.argv[reportIndex + 1] : undefined;
assert.ok(reportIndex < 0 || reportPath, "--report requires a new output path");
const checks = [];
const started = performance.now();
const server = await createServer({
  root: resolve(root, "frontend"), configFile: false, logLevel: "silent",
  server: { middlewareMode: true, hmr: false, watch: null },
  plugins: [{
    name: "confirmation-fixture-adapter", enforce: "pre",
    transform(code, id) {
      if (id.split("?")[0].replaceAll("\\", "/") !== source) return;
      const hooks = 'import { useState } from "react";';
      const api = 'import { api, newId } from "../../shared/api";';
      assert.ok(code.includes(hooks) && code.includes(api), "ConfirmSnapshot imports changed; update fixture adapter.");
      return code.replace(hooks, "const useState = (...args) => globalThis.confirmFixture.useState(...args);")
        .replace(api, "const api = (...args) => globalThis.confirmFixture.api(...args); const newId = (...args) => globalThis.confirmFixture.newId(...args);");
    },
  }],
});
try {
  globalThis.window = { location: { hash: "", pathname: "/" } };
  globalThis.sessionStorage = { getItem: () => "", setItem: () => {} };
  globalThis.history = { replaceState: () => {} };
  const { ConfirmSnapshot } = await server.ssrLoadModule("/src/features/confirm-snapshot/index.tsx");
  const { api } = await server.ssrLoadModule("/src/shared/api/index.ts");
  const { emptySnapshot } = await server.ssrLoadModule("/src/features/edit-equipment/model.ts");
  const context = { game_id: "fixture-game", edition: "base", game_build: "fixture-build", mode: "softcore", season: "fixture-season", ruleset_id: "fixture-rules", content_entitlements: [] };
  const facts = { ...emptySnapshot(context), captured_at: "2026-01-01T00:00:00.123Z",
    evidence: [{ id: "e1", kind: "manual_confirmation", source_ref: "observation://old", captured_at: "2026-01-01T00:00:00.123Z", verification: "confirmed", conflicts: [] }], evidence_ids: ["e1"] };
  facts.candidate_item.evidence_ids = ["e1"];
  const capture = { observation_id: "capture-1", method: "ocr", image_ref: "capture://1", bounds: {}, raw_text: "Fixture", capture_context: { game_id: "fixture-game", captured_at_ms: 1767225600123 } };
  const make = (seed = {}) => {
    const state = [false, false, undefined];
    let cursor = 0, serial = 0;
    const calls = [], completed = [], errors = [], busy = [];
    const render = () => {
      cursor = 0;
      const tree = ConfirmSnapshot({
        onBusyChange: value => busy.push(value), draftApplied: seed.draftApplied ?? true,
        capture: seed.capture === null ? undefined : seed.capture ?? capture, facts: seed.facts ?? facts,
        rawText: seed.rawText ?? "Fixture manual text", profileId: seed.profileId ?? "fixture-profile", revision: seed.revision ?? 4,
        onConfirmed: (...args) => completed.push(args), onError: message => errors.push(message),
      });
      assert.equal(cursor, state.length, "ConfirmSnapshot hook order changed.");
      return tree;
    };
    globalThis.confirmFixture = {
      useState(initial) { const i = cursor++; return [state[i] ?? initial, value => { state[i] = typeof value === "function" ? value(state[i]) : value; }]; },
      newId(prefix) { return prefix + "-stable-" + (++serial); },
      async api(path, body) {
        calls.push({ path, body });
        if (seed.wait) await seed.wait;
        const response = path === "profile/confirmations" ? seed.responses?.shift() : undefined;
        if (response?.httpError) throw new Error(response.message);
        if (path === "profile/confirmations") return { revision: 5, facts: body.facts, facts_hash: "fixture-hash", build_hash: "fixture-build-hash", ...(response ?? {}) };
        return { ...body };
      },
    };
    return { render, state, calls, completed, errors, busy };
  };
  function* nodes(value) {
    if (Array.isArray(value)) { for (const child of value) yield* nodes(child); }
    else if (value && typeof value === "object" && value.props) { yield value; yield* nodes(value.props.children); }
  }
  const find = (tree, test) => { const n = [...nodes(tree)].find(test); assert.ok(n, "Expected component control missing."); return n; };
  const button = h => find(h.render(), n => n.type === "button");
  const checkBox = h => find(h.render(), n => n.type === "input" && n.props.type === "checkbox");
  const accept = h => checkBox(h).props.onChange({ target: { checked: true } });
  const submit = async h => { accept(h); await button(h).props.onClick(); };
  const check = async (name, fn) => { try { await fn(); checks.push({ name, passed: true }); } catch (error) { checks.push({ name, passed: false, error: error.message }); } };

  const confirmBody = h => h.calls.find(call => call.path === "profile/confirmations").body;
  const realProfile = (calls, preparationIntent = null) => {
    const python = `
import json
from pathlib import Path
import sys
import tempfile
from contracts import DomainError
from services.profile.app import Profile

payload = json.load(sys.stdin)
calls = payload["calls"]
responses = []
preparation = None
with tempfile.TemporaryDirectory(prefix="lootweave-confirmation-") as directory:
    app = Profile(Path(directory))
    saved = None
    for call in calls:
        path = "/v1/" + call["path"].removeprefix("profile/")
        try:
            result = app.handle("POST", path, call["body"])
            responses.append({"path": call["path"], "result": result})
            if path == "/v1/confirmations":
                saved = result
        except DomainError as error:
            responses.append({"path": call["path"], "error": error.code, "status": error.status})
    with app.connect() as db:
        counts = {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                  for table in ("observations", "revisions", "confirmations")}
    reopened = Profile(Path(directory)).read(saved["profile_id"], saved["revision"]) if saved else None
    if saved and payload["intent"] is not None:
        from services.evaluation.app import Evaluation
        from services.knowledge.app import Knowledge
        class API:
            def __init__(self, service): self.service = service
            def call(self, method, route, body=None):
                if self.service is None: raise AssertionError("live source dependency used during replay")
                return self.service.handle(method, route, body or {})
        knowledge = Knowledge(Path.cwd() / "knowledge-packs")
        pack = next(row for row in knowledge.handle("GET", "/v1/packs", {})["packs"] if row["execution_policy"] == "synthetic_only")
        evaluator = Evaluation(Path(directory), API(app), API(knowledge))
        result = evaluator.create({"request_id": "confirmation-preparation", "profile_id": saved["profile_id"],
            "profile_revision": saved["revision"], "pack_id": pack["pack_id"], "pack_version": pack["version"],
            "pack_hash": pack["pack_hash"], "intent": payload["intent"]})
        evaluator = Evaluation(Path(directory), API(None), API(None))
        replayed = [evaluator.replay("confirmation-preparation")["identical"] for _ in range(10)]
        preparation = {"result": result, "replayed": replayed}
print(json.dumps({"responses": responses, "counts": counts, "reopened": reopened, "preparation": preparation}, ensure_ascii=True))
`;
    const result = spawnSync(process.env.LOOTWEAVE_PYTHON || "python", ["-c", python], {
      cwd: root, encoding: "utf8", input: JSON.stringify({ calls, intent: preparationIntent }), windowsHide: true,
      timeout: 10000, maxBuffer: 4 * 1024 * 1024,
      env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" },
    });
    assert.ifError(result.error);
    assert.equal(result.status, 0, `Real Profile fixture failed: ${result.stderr}`);
    return JSON.parse(result.stdout);
  };

  await check("manual preparation confirmation reaches real SQLite evaluation and frozen replay", async () => {
    const produced = spawnSync(process.env.LOOTWEAVE_PYTHON || "python", ["-c", "import json; from tests.test_preparation import prepared_case; f,p=prepared_case(); print(json.dumps({'facts':f,'intent':p}))"],
      { cwd: root, windowsHide: true, encoding: "utf8", timeout: 10000 });
    assert.ifError(produced.error);
    assert.equal(produced.status, 0, produced.stderr);
    const fixture = JSON.parse(produced.stdout);
    const h = make({ facts: fixture.facts, capture: null, profileId: "quoted-confirmation", revision: 0 });
    await submit(h);
    const saved = confirmBody(h).facts;
    const newEvidence = saved.evidence.at(-1).id;
    assert.ok(saved.owned_resources.balances[0].evidence_ids.includes(newEvidence));
    assert.ok(saved.preparation_options.every(option => option.evidence_ids.includes(newEvidence) && option.result.evidence_ids.includes(newEvidence)));
    assert.deepEqual(saved.preparation_options[1].input, fixture.facts.preparation_options[1].input);
    const verified = realProfile(h.calls, fixture.intent);
    assert.deepEqual(verified.counts, { observations: 1, revisions: 1, confirmations: 1 });
    assert.equal(verified.preparation.result.future_preparation[0].status, "feasible");
    assert.equal(verified.preparation.result.future_preparation[0].resources[0].cost, 12);
    assert.ok(verified.preparation.result.reasons.some(reason => reason.kind === "future_use" && reason.capability === "fire_focus"));
    assert.deepEqual(verified.preparation.replayed, Array(10).fill(true));
    assert.deepEqual(verified.reopened.facts, saved);
  });

  await check("capture time renders exact millisecond UTC", () => {
    const html = renderToStaticMarkup(make().render());
    assert.ok(html.includes('<time dateTime="2026-01-01T00:00:00.123Z">2026-01-01T00:00:00.123Z</time>'));
  });
  await check("manual input without capture time remains usable", async () => {
    const h = make({ capture: null });
    assert.equal(button(h).props.disabled, true);
    accept(h);
    assert.equal(button(h).props.disabled, false);
    await button(h).props.onClick();
    assert.equal(h.completed.length, 1);
  });
  for (const status of ["verified", "not_recorded", undefined]) await check(`confirmation accepts ${status ?? "legacy"} response and preserves fact time`, async () => {
    const h = make({ responses: [{ observation_time_status: status }] });
    await submit(h);
    assert.equal(h.completed.length, 1);
    assert.equal(h.completed[0][1].captured_at, facts.captured_at);
  });
  for (const status of ["conflict", "unavailable", "future_unknown"]) await check(`confirmation blocks ${status} response`, async () => {
    const h = make({ responses: [{ observation_time_status: status }] });
    await submit(h);
    assert.equal(h.completed.length, 0);
    assert.ok(h.errors.some(value => value.includes("采集时间") || value.includes("核对时间")));
  });
  await check("HTTP 400 observation time conflict maps to clear Chinese", async () => {
    globalThis.fetch = async (url, options) => url === "/api/runtime/ensure"
      ? { ok: true, json: async () => ({ service: JSON.parse(options.body).service, state: "ready", generation: 1 }) }
      : { ok: false, status: 400, json: async () => ({ error: "observation_time_conflict" }) };
    await assert.rejects(api("profile/confirmations", {}), /关联依据的采集时间与原始截图不一致/);
    globalThis.fetch = async (url, options) => url === "/api/runtime/ensure"
      ? { ok: true, json: async () => ({ service: JSON.parse(options.body).service, state: "ready", generation: 1 }) }
      : { ok: false, status: 400, json: async () => ({ error: "profile_observation_time_conflict" }) };
    await assert.rejects(api("profile/confirmations", {}), /原始采集时间存在冲突或无法核验/);
    globalThis.fetch = async (url, options) => url === "/api/runtime/ensure"
      ? { ok: true, json: async () => ({ service: JSON.parse(options.body).service, state: "ready", generation: 1 }) }
      : { ok: false, status: 400, json: async () => ({ error: "invalid_capture_time" }) };
    await assert.rejects(api("profile/confirmations", {}), /原始采集时间无效/);
  });
  for (const [name, seed] of [["game conflict", { facts: { ...facts, context: { ...facts.context, game_id: "other" } } }], ["unapplied draft", { draftApplied: false }]]) await check(`button is disabled for ${name}`, () => assert.equal(button(make(seed)).props.disabled, true));
  await check("button is disabled until explicit confirmation", () => assert.equal(button(make()).props.disabled, true));
  await check("busy notification and failed request restore controls", async () => {
    const h = make({ responses: [{ httpError: true, message: "fixture failure" }] });
    await submit(h);
    assert.deepEqual(h.busy, [true, false]);
    assert.equal(button(h).props.disabled, false);
    assert.ok(h.errors.includes("fixture failure"));
  });
  await check("retry after failed confirmation reuses request ID", async () => {
    const h = make({ responses: [{ httpError: true, message: "retry" }, { observation_time_status: "verified" }] });
    await submit(h);
    await button(h).props.onClick();
    const confirmations = h.calls.filter(c => c.path === "profile/confirmations");
    assert.equal(confirmations.length, 2);
    assert.equal(confirmations[0].body.request_id, confirmations[1].body.request_id);
    assert.deepEqual(confirmations[0].body, confirmations[1].body);
    assert.deepEqual(h.calls[0], h.calls[2]);
  });
  await check("first manual emptySnapshot saves through the real Profile SQLite service", async () => {
    const initial = emptySnapshot();
    const oldIds = [...initial.evidence_ids];
    initial.candidate_item.affixes = [{ id: "vitality", value: 42, unit: "points", evidence_ids: [...oldIds] }];
    initial.candidate_item.embedded_items = [{ id: "socketed", effects: [], evidence_ids: [...oldIds] }];
    initial.equipped_items.head = { ...structuredClone(initial.candidate_item), instance_id: "head-item", slot: "head" };
    for (const key of ["skills", "talents", "paragon", "runes", "companions", "temporary_effects"]) {
      initial[key] = [{ id: key + "-input", rank: 1, effects: [], evidence_ids: [...oldIds] }];
    }
    initial.observed_panel = [{ stat: "vitality", value: 42, unit: "points", source_ids: [initial.candidate_item.instance_id], evidence_ids: [...oldIds] }];
    const original = structuredClone(initial);
    const h = make({ capture: null, facts: initial, revision: 0 });
    await submit(h);
    const body = confirmBody(h);
    const manual = body.facts.evidence.find(evidence => evidence.source_ref === "observation://" + body.observation_id);
    assert.ok(manual);
    assert.equal(manual.kind, "manual_confirmation");
    assert.equal(manual.captured_at, initial.captured_at);
    assert.deepEqual(body.facts.evidence.slice(0, initial.evidence.length), initial.evidence);
    assert.deepEqual(initial, original);
    assert.deepEqual(body.facts.evidence_ids, [...oldIds, manual.id]);
    for (const item of [...Object.values(body.facts.equipped_items), body.facts.candidate_item]) {
      for (const record of [item, ...item.affixes, ...item.embedded_items]) assert.deepEqual(record.evidence_ids, [...oldIds, manual.id]);
    }
    for (const key of ["skills", "talents", "paragon", "runes", "companions", "temporary_effects", "observed_panel"]) {
      assert.deepEqual(body.facts[key][0].evidence_ids, [...oldIds, manual.id]);
    }
    const actual = realProfile(h.calls);
    assert.ok(actual.responses.every(response => !response.error));
    assert.equal(actual.reopened.revision, 1);
    assert.equal(actual.reopened.observation_time_status, "not_recorded");
    assert.deepEqual(actual.reopened.facts, body.facts);
    assert.deepEqual(actual.counts, { observations: 1, revisions: 1, confirmations: 1 });
  });
  for (const existingLink of [false, true]) await check(`OCR ${existingLink ? "reuses" : "adds"} its link and preserves older sources in real Profile storage`, async () => {
    const initial = structuredClone(facts);
    initial.captured_at = "2025-12-31T23:00:00Z";
    initial.evidence[0] = { ...initial.evidence[0], kind: "ocr_confirmation", captured_at: initial.captured_at };
    if (existingLink) initial.evidence.push({ id: "current-ocr", kind: "ocr_confirmation", source_ref: "observation://" + capture.observation_id, captured_at: "2026-01-01T00:00:00.123Z", verification: "confirmed", conflicts: [] });
    const original = structuredClone(initial);
    const h = make({ facts: initial, revision: 0 });
    await submit(h);
    const body = confirmBody(h);
    const linked = body.facts.evidence.filter(evidence => evidence.source_ref === "observation://" + capture.observation_id);
    assert.equal(linked.length, 1);
    assert.equal(linked[0].captured_at, "2026-01-01T00:00:00.123Z");
    assert.equal(linked[0].kind, "ocr_confirmation");
    if (existingLink) assert.equal(linked[0].id, "current-ocr");
    assert.deepEqual(body.facts.evidence.slice(0, initial.evidence.length), initial.evidence);
    assert.ok(body.facts.evidence_ids.includes(linked[0].id));
    assert.equal(body.facts.captured_at, initial.captured_at);
    assert.deepEqual(body.facts.candidate_item, initial.candidate_item);
    for (const key of ["equipped_items", "skills", "talents", "paragon", "runes", "companions", "temporary_effects", "observed_panel"]) assert.deepEqual(body.facts[key], initial[key]);
    assert.deepEqual(initial, original);
    const actual = realProfile(h.calls);
    assert.ok(actual.responses.every(response => !response.error));
    assert.equal(actual.reopened.observation_time_status, "verified");
    assert.deepEqual(actual.reopened.facts, body.facts);
  });
  await check("an existing mismatched OCR clock is preserved and rejected by real Profile", async () => {
    const initial = structuredClone(facts);
    initial.evidence.push({ id: "wrong-time", kind: "ocr_confirmation", source_ref: "observation://" + capture.observation_id, captured_at: "2026-01-01T00:00:00Z", verification: "confirmed", conflicts: [] });
    const h = make({ facts: initial, revision: 0 });
    await submit(h);
    assert.deepEqual(confirmBody(h).facts.evidence, initial.evidence);
    const actual = realProfile(h.calls);
    assert.equal(actual.responses[1].error, "observation_time_conflict");
    assert.equal(actual.responses[1].status, 400);
    assert.equal(actual.counts.revisions, 0);
    assert.equal(actual.counts.confirmations, 0);
    assert.equal(actual.reopened, null);
  });
  await check("manual confirmation retry keeps identical evidence and writes one SQLite revision", async () => {
    const initial = emptySnapshot();
    const h = make({ capture: null, facts: initial, revision: 0, responses: [{ httpError: true, message: "response lost" }] });
    await submit(h);
    await button(h).props.onClick();
    assert.deepEqual(h.calls.slice(0, 2), h.calls.slice(2));
    const actual = realProfile(h.calls);
    assert.ok(actual.responses.every(response => !response.error));
    assert.deepEqual(actual.responses[1].result, actual.responses[3].result);
    assert.deepEqual(actual.counts, { observations: 1, revisions: 1, confirmations: 1 });
  });
} finally {
  await server.close();
  delete globalThis.confirmFixture;
}
const sha = path => createHash("sha256").update(readFileSync(resolve(root, path))).digest("hex");
const report = { tests: checks.length, passed: checks.filter(c => c.passed).length, checks,
  elapsed_seconds: (performance.now() - started) / 1000,
  source_sha256: { [sourcePath]: sha(sourcePath), [apiPath]: sha(apiPath) },
  scope: "Direct ConfirmSnapshot rendering/handlers, plus generated requests validated by the real Profile service in temporary SQLite storage. Does not cover React scheduling, native IPC, or real-game acceptance.",
  input_automation: false };
if (reportPath) writeFileSync(resolve(reportPath), JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
console.log(JSON.stringify({ ...report, checks: checks.filter(c => !c.passed) }));
if (report.passed !== report.tests) process.exitCode = 1;
