// Direct ConfirmSnapshot rendering/handler checks with fixture hooks and API responses.
// These checks do not cover React scheduling, native IPC, desktop input, or real-game acceptance.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
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
  const facts = {
    context: { game_id: "fixture-game", edition: "base", game_build: "fixture-build", mode: "softcore", season: "fixture-season", ruleset_id: "fixture-rules", content_entitlements: [] },
    captured_at: "2026-01-01T00:00:00.123Z", evidence: [{ id: "e1", kind: "manual_confirmation", source_ref: "observation://old", captured_at: "2026-01-01T00:00:00.123Z", verification: "confirmed", conflicts: [] }],
  };
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
        rawText: seed.rawText ?? "Fixture manual text", profileId: "fixture-profile", revision: 4,
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
    globalThis.fetch = async () => ({ ok: false, status: 400, json: async () => ({ error: "observation_time_conflict" }) });
    await assert.rejects(api("profile/confirmations", {}), /关联依据的采集时间与原始截图不一致/);
    globalThis.fetch = async () => ({ ok: false, status: 400, json: async () => ({ error: "profile_observation_time_conflict" }) });
    await assert.rejects(api("profile/confirmations", {}), /原始采集时间存在冲突或无法核验/);
    globalThis.fetch = async () => ({ ok: false, status: 400, json: async () => ({ error: "invalid_capture_time" }) });
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
  });
} finally {
  await server.close();
  delete globalThis.confirmFixture;
}
const sha = path => createHash("sha256").update(readFileSync(resolve(root, path))).digest("hex");
const report = { tests: checks.length, passed: checks.filter(c => c.passed).length, checks,
  elapsed_seconds: (performance.now() - started) / 1000,
  source_sha256: { [sourcePath]: sha(sourcePath), [apiPath]: sha(apiPath) },
  scope: "Direct ConfirmSnapshot component rendering and handlers with fixture hooks/API. Does not cover React scheduling, native IPC, or real-game acceptance.",
  input_automation: false };
if (reportPath) writeFileSync(resolve(reportPath), JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
console.log(JSON.stringify({ ...report, checks: checks.filter(c => !c.passed) }));
if (report.passed !== report.tests) process.exitCode = 1;
