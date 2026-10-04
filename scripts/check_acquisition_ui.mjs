// Planning component rendering and handler checks in Node; no DOM, browser or desktop input.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { createServer } from "../frontend/node_modules/vite/dist/node/index.js";
import { renderToStaticMarkup } from "../frontend/node_modules/react-dom/server.node.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const source = resolve(root, "frontend/src/features/acquisition-evidence/index.tsx").replaceAll("\\", "/");
const routeSource = resolve(root, "frontend/src/features/route-trials/index.tsx").replaceAll("\\", "/");
const pack = JSON.parse(readFileSync(resolve(root, "knowledge-packs/synthetic-leveling-1.0.0.json"), "utf8"));
const responses = process.argv[2] ? JSON.parse(readFileSync(process.argv[2], "utf8")) : {
  facts: { context: pack.context },
  pack,
  eligibility: { scope_accepted: true, sources: pack.acquisition_sources.map(s => ({ ...s, eligibility: "active" })),
    unknowns: [], notice: "Synthetic source eligibility." },
  estimate: { context: pack.context, target_event: "fixture-core-item", attempt_unit: "run",
    sample_size: 100, observed_successes: 10, estimate: .1, interval: [.05, .18], confidence_level: .95,
    method: "Wilson score interval on recorded binary outcomes", assumptions: ["Complete synthetic records."],
    notice: "Sample estimate, not a verified game probability." },
};

globalThis.window = { location: { hash: "", pathname: "/" } };
globalThis.sessionStorage = { getItem: () => "", setItem: () => {} };
globalThis.history = { replaceState: () => {} };
const server = await createServer({
  root: resolve(root, "frontend"), configFile: false, logLevel: "silent",
  server: { middlewareMode: true, hmr: false, watch: null },
  plugins: [{
    name: "acquisition-state-fixture", enforce: "pre",
    transform(code, id) {
      if (![source, routeSource].includes(id.split("?")[0].replaceAll("\\", "/"))) return;
      const declaration = 'import { useState } from "react";';
      assert.ok(code.includes(declaration), "Acquisition hook import changed; update this fixture adapter.");
      return code.replace(declaration, "const useState = (...args) => globalThis.acquisitionFixture.useState(...args);");
    },
  }],
});
const checks = [];
const started = performance.now();
try {
  const { AcquisitionEvidence } = await server.ssrLoadModule("/src/features/acquisition-evidence/index.tsx");
  const { isExactCount } = await server.ssrLoadModule("/src/shared/api/index.ts");
  const { RouteTrials } = await server.ssrLoadModule("/src/features/route-trials/index.tsx");
  const fresh = (seed = {}) => {
    const state = [false, false, seed.eligibility, seed.estimate, "fixture-core-item", "run",
      seed.attempts, seed.successes, true, true];
    let cursor = 0;
    const calls = [], errors = [];
    globalThis.acquisitionFixture = {
      useState(initial) {
        const index = cursor++;
        if (index >= state.length) throw new Error("Acquisition hook order changed.");
        if ((index === 6 || index === 7) && state[index] === undefined) {
          const count = index === 6 ? 100 : 10;
          state[index] = typeof initial === "number" ? count : String(count);
        }
        return [state[index] ?? initial, value => { state[index] = typeof value === "function" ? value(state[index]) : value; }];
      },
    };
    globalThis.fetch = async (url, options) => {
      const body = options.body ? JSON.parse(options.body) : undefined;
      calls.push({ url, body });
      if (seed.wait) await seed.wait;
      return { ok: !seed.error, json: async () => seed.error ? { error: seed.error } :
        url.endsWith("/eligibility") ? responses.eligibility : responses.estimate };
    };
    const render = () => {
      cursor = 0;
      const tree = AcquisitionEvidence({ facts: responses.facts, revision: 1, pack: responses.pack,
        onError: message => errors.push(message) });
      assert.equal(cursor, state.length, "Acquisition hook order changed.");
      return tree;
    };
    return { render, state, calls, errors };
  };
  function* nodes(value) {
    if (Array.isArray(value)) { for (const child of value) yield* nodes(child); }
    else if (value && typeof value === "object" && value.props) {
      yield value;
      yield* nodes(value.props.children);
    }
  }
  const find = (tree, predicate) => {
    const node = [...nodes(tree)].find(predicate);
    assert.ok(node, "Expected acquisition control was not rendered.");
    return node;
  };
  const button = tree => find(tree, n => n.type === "button" && ["提交完整观察样本", "提交观察中…"].includes(String(n.props.children)));
  const input = (tree, label) => find(tree, n => n.type === "label" && n.props.children?.[0] === label).props.children[1];
  const confirm = harness => {
    for (const node of nodes(harness.render()))
      if (node.type === "input" && node.props.type === "checkbox") node.props.onChange({ target: { checked: true } });
  };
  const check = async (name, fn) => {
    try { await fn(); checks.push({ name, passed: true }); }
    catch (error) { checks.push({ name, passed: false, error: error.message }); }
  };
  const routeHtml = result => {
    const state = Array(14).fill(undefined);
    state[13] = result;
    let cursor = 0;
    // ponytail: fixture hooks verify presentation; DOM rendering is needed for React scheduling.
    globalThis.acquisitionFixture = { useState(initial) {
      const index = cursor++;
      assert.ok(index < state.length, "Route hook order changed.");
      return [state[index] ?? initial, () => {}];
    } };
    const tree = RouteTrials({ facts: { ...responses.facts, character_level: 15, class_id: "sorcerer" },
      revision: 1, buildHash: "fixture-build", onError: () => {} });
    assert.equal(cursor, state.length, "Route hook order changed.");
    return renderToStaticMarkup(tree);
  };
  const row = { map_id: "fixture-map", difficulty_id: "normal", access: "active", status: "measured",
    trial_count: 1, xp_per_minute: 100, minimum_trial_rate: 100, maximum_trial_rate: 100,
    observation: "single_trial", unknowns: [] };
  const routeResult = { routes: [row], excluded_trials: [], best_measured_candidate: null, retest_recommended: false };
  await check("unusable legacy measurements have an explicit warning", () => {
    const html = routeHtml({ ...routeResult, excluded_trials: [{ trial_id: "legacy",
      reason: "uncertain_measurement_or_access", unknowns: ["trial_measurement_out_of_range"] }] });
    assert.ok(html.includes("条数值无法可靠计算的历史试验"));
  });
  await check("unknown aggregate rates stay unmeasured and warn before ranking", () => {
    const html = routeHtml({ ...routeResult, routes: [{ ...row, status: "needs_confirmation",
      xp_per_minute: null, unknowns: ["aggregate_trial_measurement_out_of_range"] }] });
    assert.ok(html.includes("累计测量超出可靠计算范围"));
    assert.ok(html.includes("未测量"));
    assert.ok(!html.includes("已测候选中最高："));
  });
  await check("small positive route rates retain a nonzero display", () => {
    assert.ok(routeHtml({ ...routeResult, routes: [{ ...row, xp_per_minute: 1 / 600 }] }).includes("1.67e-3"));
    assert.ok(routeHtml({ ...routeResult, routes: [{ ...row, xp_per_minute: 0 }] }).includes("0.00"));
  });
  await check("shared count validation preserves decimal integer input exactly", () => {
    for (const value of ["0", "100", "000100", "9007199254740991"]) assert.equal(isExactCount(value), true, value);
    for (const value of ["", " ", "-1", "1.5", "100.0", "1e3", "9007199254740991.1", "9007199254740993"])
      assert.equal(isExactCount(value), false, value);
  });
  await check("source IDs and target events use the API contract", () => {
    const html = renderToStaticMarkup(fresh({ eligibility: responses.eligibility }).render());
    for (const entry of responses.eligibility.sources) {
      assert.ok(html.includes("来源 ID：" + entry.source_id));
      assert.ok(html.includes("目标事件：" + entry.target_event));
    }
  });
  await check("estimate displays all returned version scope fields", () => {
    const html = renderToStaticMarkup(fresh({ estimate: responses.estimate }).render());
    for (const key of ["game_id", "edition", "game_build", "mode", "season", "ruleset_id"])
      assert.ok(html.includes(responses.estimate.context[key]), key + " not rendered");
    if (process.argv[3]) writeFileSync(process.argv[3] + ".html", html, { flag: "wx" });
  });
  await check("small nonzero interval bounds never render as zero", () => {
    const estimate = { ...responses.estimate, estimate: 0, interval: [0, 1e-6] };
    const html = renderToStaticMarkup(fresh({ estimate }).render());
    assert.ok(html.includes("1.0e-4%"));
  });
  await check("near-one estimates and content scope retain uncertainty", () => {
    const estimate = { ...responses.estimate, estimate: .999999, interval: [.99999, 1],
      context: { ...responses.estimate.context, content_entitlements: ["fixture-expansion"] } };
    const html = renderToStaticMarkup(fresh({ estimate }).render());
    assert.ok(html.includes("&lt;100%"));
    assert.ok(html.includes("fixture-expansion"));
  });
  for (const [attempts, successes, accepted] of [
    ["100", "", false], ["", "0", false], ["100", " ", false],
    ["9007199254740993", "1", false], ["9007199254740991.1", "1", false],
    ["1e3", "1", false], ["000100", "000001", true], ["1e400", "0", false],
    ["100", "1.5", false], ["100", "-1", false], ["100", "101", false],
    ["100", "0", true], ["9007199254740991", "9007199254740990", true],
  ]) {
    await check("count boundary " + JSON.stringify([attempts, successes]), async () => {
      const harness = fresh();
      input(harness.render(), "尝试次数").props.onChange({ target: { value: attempts } });
      input(harness.render(), "观察到成功次数").props.onChange({ target: { value: successes } });
      confirm(harness);
      const control = button(harness.render());
      assert.equal(control.props.disabled, !accepted);
      await control.props.onClick();
      assert.equal(harness.calls.length, accepted ? 1 : 0);
      if (accepted) {
        assert.equal(harness.calls[0].body.attempts, Number(attempts));
        assert.equal(harness.calls[0].body.successes, Number(successes));
        assert.deepEqual(harness.calls[0].body.context, responses.facts.context);
      }
    });
  }
  for (const label of ["目标事件", "一次尝试的单位", "尝试次数", "观察到成功次数"]) {
    await check("draft edit clears estimate and confirmations: " + label, () => {
      const harness = fresh({ estimate: responses.estimate });
      input(harness.render(), label).props.onChange({ target: { value: "2" } });
      assert.equal(harness.state[3], undefined);
      const boxes = [...nodes(harness.render())].filter(n => n.type === "input" && n.props.type === "checkbox");
      assert.ok(boxes.every(n => n.props.checked === false));
    });
  }
  await check("inflight sample disables controls and duplicate submission", async () => {
    let release;
    const wait = new Promise(resolve => { release = resolve; });
    const harness = fresh({ wait, estimate: responses.estimate });
    const request = button(harness.render()).props.onClick();
    try {
      assert.equal(harness.state[3], undefined);
      assert.ok([...nodes(harness.render())].some(n => n.type === "fieldset" && n.props.disabled));
      await button(harness.render()).props.onClick();
      assert.equal(harness.calls.length, 1);
    } finally { release(); await request; }
    assert.equal(harness.state[1], false);
  });
  await check("failed sample leaves no previous estimate", async () => {
    const harness = fresh({ error: "invalid_sample_counts", estimate: responses.estimate });
    await button(harness.render()).props.onClick();
    assert.equal(harness.state[3], undefined);
    assert.ok(harness.errors.some(value => value.includes("精确整数次数")));
    assert.equal(harness.state[1], false);
  });
} finally {
  await server.close();
  delete globalThis.acquisitionFixture;
}
const sha = path => createHash("sha256").update(readFileSync(resolve(root, path))).digest("hex");
const report = { tests: checks.length, passed: checks.filter(c => c.passed).length, checks,
  elapsed_seconds: (performance.now() - started) / 1000,
  source_sha256: { "frontend/src/features/acquisition-evidence/index.tsx": sha("frontend/src/features/acquisition-evidence/index.tsx"),
    "frontend/src/shared/api/index.ts": sha("frontend/src/shared/api/index.ts"),
    "frontend/src/features/route-trials/index.tsx": sha("frontend/src/features/route-trials/index.tsx") },
  scope: "Actual Planning component rendering and handlers with fixture state/HTTP adapters; no DOM, browser, native IPC or game acceptance.",
  input_automation: false };
if (process.argv[3]) writeFileSync(process.argv[3], JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
console.log(JSON.stringify({ ...report, checks: report.checks.filter(c => !c.passed).map(c => ({ ...c, error: c.error.slice(0,300) })) }));
if (report.passed !== report.tests) process.exitCode = 1;
