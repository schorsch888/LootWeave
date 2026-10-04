// Direct component handlers and static rendering; no browser, desktop or input automation.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { createServer } from "../frontend/node_modules/vite/dist/node/index.js";
import { renderToStaticMarkup } from "../frontend/node_modules/react-dom/server.node.js";
import { createElement } from "../frontend/node_modules/react/index.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const workbenchPath = resolve(root, "frontend/src/pages/workbench/index.tsx").replaceAll("\\", "/");
const checks = [];
const reportIndex = process.argv.indexOf("--report");
const reportPath = reportIndex >= 0 ? process.argv[reportIndex + 1] : undefined;
assert.ok(reportIndex < 0 || reportPath);
const server = await createServer({ root: resolve(root, "frontend"), configFile: false, logLevel: "silent", server: { middlewareMode: true, hmr: false, watch: null }, plugins: [{ name: "core-fixture-hooks", enforce: "pre", transform(code, id) {
  if (id.split("?")[0].replaceAll("\\", "/") !== workbenchPath) return;
  const hooks = 'import { useEffect, useRef, useState } from "react";';
  const api = 'import { api, ensureService, newId } from "../../shared/api";';
  const runtime = 'import { pollRuntime } from "../../shared/runtime";';
  assert.ok(code.includes(hooks) && code.includes(api) && code.includes(runtime));
  return code.replace(hooks, "const useEffect = (...args) => globalThis.coreFixture.useEffect(...args); const useRef = (...args) => globalThis.coreFixture.useRef(...args); const useState = (...args) => globalThis.coreFixture.useState(...args);")
    .replace(api, "const api = (...args) => globalThis.coreFixture.api(...args); const ensureService = (...args) => globalThis.coreFixture.ensureService(...args); const newId = prefix => prefix + '-' + crypto.randomUUID();")
    .replace(runtime, "const pollRuntime = (...args) => globalThis.coreFixture.pollRuntime(...args);");
} }] });
function* nodes(value) {
  if (Array.isArray(value)) for (const child of value) yield* nodes(child);
  else if (value && typeof value === "object" && value.props) { yield value; yield* nodes(value.props.children); }
}
const find = (tree, predicate) => { const node = [...nodes(tree)].find(predicate); assert.ok(node, "Expected core control missing"); return node; };
const component = (tree, name) => find(tree, n => typeof n.type === "function" && n.type.name === name);
const button = (tree, text) => find(tree, n => n.type === "button" && n.props.children === text);
const check = async (name, run) => { await run(); checks.push({ name, passed: true }); };
try {
  globalThis.window = { location: { hash: "", pathname: "/" } };
  globalThis.sessionStorage = { getItem: () => "", setItem: () => {} };
  globalThis.history = { replaceState: () => {} };
  const equipment = await server.ssrLoadModule("/src/features/edit-equipment/index.tsx");
  const model = await server.ssrLoadModule("/src/features/edit-equipment/model.ts");
  const { BuildEditor } = await server.ssrLoadModule("/src/features/edit-build/index.tsx");
  const { EvaluationCard } = await server.ssrLoadModule("/src/entities/evaluation/index.tsx");
  const { Workbench } = await server.ssrLoadModule("/src/pages/workbench/index.tsx");
  const demo = JSON.parse(readFileSync(resolve(root, "fixtures/demo.json"), "utf8"));
  const fresh = equipment.emptySnapshot();
  await check("actual draft starts empty with explicit unreviewed build and slot", () => { assert.equal(fresh.context.game_id, "deskrawl"); assert.equal(fresh.context.game_build, "unknown"); assert.deepEqual(fresh.equipped_items, {}); assert.deepEqual(fresh.skills, []); assert.equal(fresh.inventory_coverage, "unknown"); assert.ok(fresh.unknowns.includes("build_not_reviewed") && fresh.unknowns.includes("current_slot_not_reviewed")); assert.ok(fresh.candidate_item.required_level === null); });
  await check("new equipment instances are distinct and do not mutate evidence inputs", () => { const refs = ["e1"]; const one = model.emptyItem(refs), two = model.emptyItem(refs); one.evidence_ids.push("e2"); assert.notEqual(one.instance_id, two.instance_id); assert.deepEqual(refs, ["e1"]); });
  await check("OCR only fills a field after explicit mapping with its source", () => { const item = structuredClone(demo.facts.candidate_item); const frozen = JSON.stringify(item); const next = equipment.mapItemField(item, { field: "vitality", value: -12.5, unit: "percent", ambiguous: false }, "capture-input"); assert.equal(next.affixes.at(-1).value, -12.5); assert.equal(next.affixes.at(-1).unit, "percent"); assert.deepEqual(next.affixes.at(-1).evidence_ids, ["capture-input"]); assert.equal(JSON.stringify(item), frozen); assert.deepEqual(next.effects, item.effects); });
  await check("ambiguous missing and unsupported OCR fields cannot be auto-applied", () => { for (const field of [{ field: "vitality", value: 65, unit: "points", ambiguous: true }, { field: "armor", value: null, unit: "points", ambiguous: false }, { field: "armor", value: 12, unit: null, ambiguous: false }, { field: "level", value: 2.5, unit: "level", ambiguous: false }, { field: "skill", value: 1, unit: "rank", ambiguous: false }]) assert.throws(() => equipment.mapItemField(fresh.candidate_item, field, "e1")); });
  await check("OCR level is an explicitly selected item requirement not character level", () => { const field = { field: "level", value: 20, unit: "level", ambiguous: false }; assert.throws(() => equipment.mapItemField(fresh.candidate_item, field, "e1")); const next = equipment.mapItemField(fresh.candidate_item, field, "e1", true); assert.equal(next.required_level, 20); assert.equal(fresh.character_level, 1); });
  await check("clearing an actual roll leaves it missing instead of recording zero", () => { let changed; const tree = equipment.ItemEditor({ item: demo.facts.candidate_item, onChange: x => { changed = x; } }); find(tree, n => n.type === "input" && n.props["aria-label"] === "词条实际数值").props.onChange({ target: { value: "" } }); assert.ok(Number.isNaN(changed.affixes[0].value)); assert.equal(demo.facts.candidate_item.affixes[0].value, 65); });
  await check("adding an affix requires an actual value and a matching identifier", () => { let changed; const tree = equipment.ItemEditor({ item: fresh.candidate_item, onChange: x => { changed = x; } }); button(tree, "添加词条").props.onClick(); assert.ok(Number.isNaN(changed.affixes[0].value)); assert.equal(changed.affixes[0].unit, "points"); });
  await check("build review only removes its own missing-input marker", () => { let changed; const tree = BuildEditor({ facts: fresh, intent: demo.intent, onFactsChange: x => { changed = x; }, onIntentChange: () => {} }); find(tree, n => n.type === "input" && n.props.type === "checkbox" && n.props.checked === false).props.onChange({ target: { checked: true } }); assert.ok(!changed.unknowns.includes("build_not_reviewed")); assert.ok(changed.unknowns.includes("current_slot_not_reviewed")); assert.equal(fresh.unknowns.length, 2); });
  await check("future goal changes increment intent without changing confirmed facts", () => { let changed; const before = JSON.stringify(fresh); const tree = BuildEditor({ facts: fresh, intent: demo.intent, onFactsChange: () => assert.fail("facts changed"), onIntentChange: x => { changed = x; } }); button(tree, "添加未来构筑").props.onClick(); assert.equal(changed.revision, demo.intent.revision + 1); assert.equal(changed.future_builds.length, 1); assert.equal(changed.future_builds[0].feasibility, ""); assert.equal(JSON.stringify(fresh), before); });
  const states = [], effects = [], dependencies = [], cleanups = [], calls = []; let cursor = 0, effectCursor = 0, publishStatus;
  const starting = { core_ready: false, degraded: false, startup_policy: "on-demand", services: { profile: { state: "starting", generation: 1 }, knowledge: { state: "starting", generation: 1 }, evaluation: { state: "starting", generation: 1 } } };
  const ready = { ...starting, core_ready: true, services: Object.fromEntries(["profile", "knowledge", "evaluation"].map(name => [name, { state: "ready", generation: 1 }])) };
  globalThis.coreFixture = {
    useState(initial) { const i = cursor++; if (!(i in states)) states[i] = typeof initial === "function" ? initial() : initial; return [states[i], value => { states[i] = typeof value === "function" ? value(states[i]) : value; }]; },
    useRef(initial) { const i = cursor++; if (!(i in states)) states[i] = { current: initial }; return states[i]; },
    useEffect(run, next) { const i = effectCursor++; if (!dependencies[i] || next.some((value, index) => !Object.is(value, dependencies[i][index]))) { dependencies[i] = next; effects.push(() => { cleanups[i]?.(); cleanups[i] = run(); }); } },
    pollRuntime(onStatus) { publishStatus = onStatus; onStatus(starting); return { refresh() {}, stop() {} }; },
    async ensureService() { assert.fail("Unexpected startup retry"); },
    async api(path) { calls.push(path); if (path === "knowledge/packs") return { packs: [{ pack_id: "deskrawl-sorcerer-leveling", version: "0.6.0-research", pack_hash: "fixture", context: fresh.context, class_id: "sorcerer", scenario: "leveling", execution_policy: "research_only" }] }; if (path === "demo") return demo; throw new Error("Unexpected fixture API: " + path); },
  };
  const render = () => { cursor = 0; effectCursor = 0; return Workbench(); };
  const settle = async () => { for (let i = 0; i < 3; i++) { render(); for (const run of effects.splice(0)) run(); await new Promise(resolve => setImmediate(resolve)); } };
  await settle();
  await check("real manual draft stays available while core startup gates catalog and confirmation", () => { const tree = render(); assert.deepEqual(calls, []); assert.equal(component(tree, "EquipmentEditor").props.facts.context.game_id, "deskrawl"); assert.equal(component(tree, "ConfirmSnapshot").props.draftApplied, false); assert.equal(button(tree, "新建真实录入").props.disabled, false); assert.equal(button(tree, "解释保留价值与换装变化 →").props.disabled, true); });
  publishStatus(ready); await settle();
  await check("workbench defaults to real fields and only loads demo on request", () => { const tree = render(); assert.equal(component(tree, "EquipmentEditor").props.facts.context.game_id, "deskrawl"); assert.deepEqual(calls, ["knowledge/packs"]); assert.ok(button(tree, "加载合成示例")); });
  await check("saved profile reopens the exact SQLite revision and editing requires reconfirmation", () => { const facts = { ...fresh, candidate_item: { ...fresh.candidate_item, name: "Personal fixture" } }; component(render(), "ProfileLibrary").props.onOpen({ profile_id: "saved-fixture", revision: 7, facts, build_hash: "hash", facts_hash: "facts", observation_time_status: "not_recorded" }); assert.equal(component(render(), "ConfirmSnapshot").props.revision, 7); assert.equal(component(render(), "EquipmentEditor").props.facts, facts); assert.equal(button(render(), "解释保留价值与换装变化 →").props.disabled, false); component(render(), "EquipmentEditor").props.onChange({ ...facts, character_level: 25 }); assert.equal(button(render(), "解释保留价值与换装变化 →").props.disabled, true); });
  await check("optional readiness updates preserve the edited profile identity and draft", () => { const before = component(render(), "ConfirmSnapshot").props; publishStatus({ ...ready, services: { ...ready.services, ocr: { state: "ready", generation: 2 } } }); const after = component(render(), "ConfirmSnapshot").props; assert.equal(after.facts, before.facts); assert.equal(after.profileId, before.profileId); assert.equal(after.revision, before.revision); assert.equal(after.draftApplied, before.draftApplied); });
  await check("pending operations disable profile and history switches", () => { component(render(), "ConfirmSnapshot").props.onBusyChange(true); assert.equal(component(render(), "ProfileLibrary").props.busy, true); assert.equal(component(render(), "EvaluationHistory").props.disabled, true); assert.equal(button(render(), "新建真实录入").props.disabled, true); component(render(), "ConfirmSnapshot").props.onBusyChange(false); });
  await check("source-clock conflicts remain unconfirmed after reopening", () => { component(render(), "ProfileLibrary").props.onOpen({ profile_id: "clock-fixture", revision: 2, facts: fresh, build_hash: "hash", facts_hash: "facts", observation_time_status: "conflict" }); assert.equal(button(render(), "解释保留价值与换装变化 →").props.disabled, true); });
  await check("capture import retains its clock and leaves fields pending", () => { const capture = { observation_id: "fixture-capture", fields: [{ field: "vitality", value: 65, unit: "points", ambiguous: false }], raw_text: "Vitality +65", capture_context: { game_id: "deskrawl", captured_at_ms: 1767225600123 } }; component(render(), "CaptureObservationForm").props.onCaptured(capture); const facts = component(render(), "EquipmentEditor").props.facts; const evidence = facts.evidence.find(e => e.source_ref === "observation://fixture-capture"); assert.equal(evidence.captured_at, "2026-01-01T00:00:00.123Z"); assert.deepEqual(facts.candidate_item.affixes, []); assert.ok(facts.unknowns.includes("ocr_fields_not_mapped")); });
  await check("real comparison shows raw signed differences and unit conflicts without a DPS verdict", () => { const result = { evaluation_id: "render-fixture", retention: "needs_confirmation", comparison: { status: "blocked", scope_compatible: false, lost_capabilities: [], gained_capabilities: [], missing_requirements: [], equip_blockers: [], before: [], after: [], item_rolls: { current_item: { name: "Current", instance_id: "one" }, candidate_item: { name: "Candidate", instance_id: "two" }, rows: [{ affix_id: "vitality", current_value: 40, candidate_value: 65, current_unit: "points", candidate_unit: "points", delta: 25, status: "comparable", input_evidence_ids: ["e1"] }, { affix_id: "armor", current_value: 10, candidate_value: 5, current_unit: "points", candidate_unit: "percent", delta: null, status: "unit_mismatch", input_evidence_ids: ["e1"] }] } }, blockers: ["game_mechanics_not_accepted"], reasons: [], pin: { context: fresh.context, profile_revision: 7, pack_version: "research", evaluator_version: "0.1.5", intent_revision: 1 } }; const html = renderToStaticMarkup(createElement(EvaluationCard, { result, onReplay: () => {}, replaying: false, replayed: false })); assert.ok(html.includes("+25 点") && html.includes("单位不同，未相减") && html.includes("实际词条对比") && html.includes("需要补充确认")); assert.ok(!html.includes("当前使用合成示例")); });
  await check("explicit demo activation replaces only the requested draft and resets profile revision", async () => { await button(render(), "加载合成示例").props.onClick(); const tree = render(); assert.equal(component(tree, "EquipmentEditor").props.facts, demo.facts); assert.equal(component(tree, "ConfirmSnapshot").props.revision, 0); assert.ok(calls.includes("demo")); });
  for (const cleanup of cleanups) cleanup?.();
  console.log("Core UI fixture checks: " + checks.length + " passed; no browser or desktop input.");
} catch (error) { checks.push({ passed: false, error: error.message }); process.exitCode = 1; console.error(error); }
finally { await server.close(); if (reportPath) writeFileSync(reportPath, JSON.stringify({ scope: "Direct React handlers and static rendering; not GUI, scheduling, OCR or real-game acceptance.", passed: !process.exitCode, checks }, null, 2) + "\n", { flag: "wx" }); }
