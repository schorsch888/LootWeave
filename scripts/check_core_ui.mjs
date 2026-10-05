// Direct component handlers and static rendering; no browser, desktop or input automation.
import assert from "node:assert/strict";
import { readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { createServer } from "../frontend/node_modules/vite/dist/node/index.js";
import { renderToStaticMarkup } from "../frontend/node_modules/react-dom/server.node.js";
import { createElement } from "../frontend/node_modules/react/index.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const workbenchPath = resolve(root, "frontend/src/pages/workbench/index.tsx").replaceAll("\\", "/");
const equipmentPath = resolve(root, "frontend/src/features/edit-equipment/index.tsx").replaceAll("\\", "/");
const checks = [];
const reportIndex = process.argv.indexOf("--report");
const reportPath = reportIndex >= 0 ? process.argv[reportIndex + 1] : undefined;
assert.ok(reportIndex < 0 || reportPath);
const server = await createServer({ root: resolve(root, "frontend"), configFile: false, logLevel: "silent", server: { middlewareMode: true, hmr: false, watch: null }, plugins: [{ name: "core-fixture-hooks", enforce: "pre", transform(code, id) {
  const path = id.split("?")[0].replaceAll("\\", "/");
  if (path === equipmentPath) {
    const hook = 'import { useState } from "react";';
    assert.ok(code.includes(hook));
    return code.replace(hook, "const useState = (...args) => globalThis.equipmentFixture.useState(...args);");
  }
  if (path !== workbenchPath) return;
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
  const { SourceList } = await server.ssrLoadModule("/src/entities/build-source/index.tsx");
  const { BuildEditor } = await server.ssrLoadModule("/src/features/edit-build/index.tsx");
  const { OwnedResourcesEditor } = await server.ssrLoadModule("/src/features/edit-owned-resources/index.tsx");
  const { EvaluationCard } = await server.ssrLoadModule("/src/entities/evaluation/index.tsx");
  const { Workbench } = await server.ssrLoadModule("/src/pages/workbench/index.tsx");
  const demo = JSON.parse(readFileSync(resolve(root, "fixtures/demo.json"), "utf8"));
  const fresh = equipment.emptySnapshot();
  const renderedPreparations = spawnSync(process.env.LOOTWEAVE_PYTHON || "python", ["-c", "import copy,json; from tests.test_preparation import prepared_case,run_case; f,p=prepared_case(); rows=[run_case(f,p)]; f['owned_resources']['balances'][0]['amount']=8; rows.append(run_case(f,p)); del f['owned_resources']; rows.append(run_case(f,p)); print(json.dumps(rows))"],
    { cwd: root, windowsHide: true, encoding: "utf8", timeout: 10000 });
  assert.ifError(renderedPreparations.error);
  assert.equal(renderedPreparations.status, 0, renderedPreparations.stderr);
  const preparationRows = JSON.parse(renderedPreparations.stdout);
  await check("frozen preparation rendering distinguishes feasible, shortage and unknown amounts", () => {
    const html = preparationRows.map(result => renderToStaticMarkup(createElement(EvaluationCard, { result, onReplay() {}, replaying: false, replayed: false })));
    assert.ok(html[0].includes("满足已记录的准备条件"));
    assert.ok(html[0].includes("fixture-fire-bolt · 3 级 · 角色"));
    assert.ok(html[0].includes("预计改后物品"));
    assert.ok(html[1].includes("当前条件不满足"));
    assert.ok(html[1].includes("<td>fixture-shard</td><td>12</td><td>8</td><td>12</td><td>4</td>"));
    assert.ok(html[2].includes("准备条件待确认"));
    assert.ok(html[2].includes("<td>fixture-shard</td><td>12</td><td>待核对</td><td>12</td><td>待核对</td>"));
    assert.ok(html.every(markup => markup.includes("条件满足也不代表 DPS 或真实游戏机制已验证")));
  });

  await check("resource review keeps absent quantities unknown and does not alter equipment", () => {
    let changed;
    const original = JSON.stringify(fresh);
    button(OwnedResourcesEditor({ facts: fresh, onChange: x => { changed = x; } }), "开始核对资源").props.onClick();
    assert.deepEqual(changed.owned_resources, { coverage: "partial", balances: [] });
    assert.equal(JSON.stringify(fresh), original);
    button(OwnedResourcesEditor({ facts: changed, onChange: x => { changed = x; } }), "添加材料或货币").props.onClick();
    assert.ok(Number.isNaN(changed.owned_resources.balances[0].amount));
    assert.deepEqual(changed.owned_resources.balances[0].evidence_ids, fresh.evidence_ids);
  });
  await check("resource changes invalidate complete coverage and preserve evidence", () => {
    let changed;
    const facts = { ...demo.facts, owned_resources: { coverage: "complete", balances: [{ resource_id: "fixture-shard", amount: 20, evidence_ids: ["demo-input"] }] } };
    const tree = OwnedResourcesEditor({ facts, onChange: x => { changed = x; } });
    find(tree, n => n.props["aria-label"] === "第 1 项资源个数").props.onChange({ target: { value: "" } });
    assert.equal(changed.owned_resources.coverage, "partial");
    assert.ok(Number.isNaN(changed.owned_resources.balances[0].amount));
    assert.equal(facts.owned_resources.balances[0].amount, 20);
  });
  await check("new preparation quote records a projection and unknown cost rather than changing actual equipment", () => {
    let changed;
    const before = JSON.stringify(demo.facts);
    button(equipment.PreparationOptionsEditor({ facts: demo.facts, onChange: x => { changed = x; } }), "添加装备改造方案").props.onClick();
    const quote = changed.preparation_options[0];
    assert.equal(quote.result.record_kind, "projected_item");
    assert.deepEqual(quote.input, demo.facts.candidate_item);
    assert.equal(quote.costs, null);
    assert.equal(quote.requirements.unlock_state, "unknown");
    assert.ok(quote.unknowns.includes("outcome_not_confirmed"));
    assert.equal(JSON.stringify(demo.facts), before);
  });
  const projection = () => { const input = structuredClone(demo.facts.candidate_item); return { id: "upgrade", kind: "equipment", target_id: input.instance_id,
    input, result: { ...structuredClone(input), record_kind: "projected_item" }, context: structuredClone(demo.facts.context), class_id: demo.facts.class_id,
    requirements: { required_level: 1, max_rank: null, unlock_state: "unlocked" }, costs: [{ resource_id: "shard", amount: 5 }, { resource_id: "gold", amount: 100 }],
    unknowns: [], evidence_ids: ["demo-input"] }; };
  await check("fee confirmation preserves paid draft rows across uncheck and recheck", () => {
    let facts = { ...demo.facts, preparation_options: [projection()] };
    const render = () => equipment.PreparationOptionsEditor({ facts, onChange: x => { facts = x; } });
    find(render(), n => n.props["aria-label"] === "已核对方案全部费用").props.onChange({ target: { checked: false } });
    assert.equal(facts.preparation_options[0].costs.length, 2);
    assert.ok(facts.preparation_options[0].unknowns.includes("costs_not_confirmed"));
    find(render(), n => n.props["aria-label"] === "已核对方案全部费用").props.onChange({ target: { checked: true } });
    assert.deepEqual(facts.preparation_options[0].costs, projection().costs);
    assert.ok(!facts.preparation_options[0].unknowns.includes("costs_not_confirmed"));
  });
  await check("equipment projection edits invalidate result review while keeping actual instance unchanged", () => {
    let changed;
    const facts = { ...demo.facts, preparation_options: [projection()] };
    const tree = equipment.PreparationOptionsEditor({ facts, onChange: x => { changed = x; } });
    const editor = component(tree, "ItemEditor");
    editor.props.onChange({ ...editor.props.item, upgrade_state: { known: true, level: 2 } });
    assert.ok(changed.preparation_options[0].unknowns.includes("outcome_not_confirmed"));
    assert.equal(changed.preparation_options[0].result.upgrade_state.level, 2);
    assert.deepEqual(changed.candidate_item, facts.candidate_item);
  });
  await check("future selection retains planned skill rank and actor without mutating confirmed facts", () => {
    let changed;
    const quote = { ...projection(), id: "learn", kind: "skill", target_id: "fixture-fire-bolt", input: null,
      result: { id: "fixture-fire-bolt", rank: 4, actor: "hero", effects: [], evidence_ids: ["demo-input"] } };
    const facts = { ...demo.facts, preparation_options: [quote] };
    const purpose = { ...demo.intent, allowed_build_changes: ["skills"], future_builds: [{ skills: demo.facts.skills.map(s => s.id), conditions: {}, feasibility: "owned", preparation_options: [] }] };
    const tree = BuildEditor({ facts, intent: purpose, onFactsChange: () => assert.fail("facts changed"), onIntentChange: x => { changed = x; } });
    find(tree, n => n.props["data-preparation-id"] === "learn").props.onChange({ target: { checked: true } });
    assert.ok(changed.future_builds[0].skills.includes("fixture-fire-bolt"));
    assert.deepEqual(changed.future_builds[0].preparation_options, ["learn"]);
    assert.equal(changed.revision, purpose.revision + 1);
    const html = renderToStaticMarkup(createElement(BuildEditor, { facts, intent: changed, onFactsChange() {}, onIntentChange() {} }));
    assert.ok(html.includes("fixture-fire-bolt · 4 级 · 角色"));
    assert.ok(!facts.skills.some(skill => skill.id === "fixture-fire-bolt"));
  });
  await check("resource budget accepts explicit zero and leaves blank unknown", () => {
    let changed;
    const purpose = { ...demo.intent, budget: { resource_limits: [{ resource_id: "shard", amount: 5 }] } };
    const render = intent => BuildEditor({ facts: demo.facts, intent, onFactsChange() {}, onIntentChange: x => { changed = x; } });
    find(render(purpose), n => n.props["aria-label"] === "预算上限").props.onChange({ target: { value: "0" } });
    assert.equal(changed.budget.resource_limits[0].amount, 0);
    assert.equal(changed.revision, purpose.revision + 1);
    find(render(changed), n => n.props["aria-label"] === "预算上限").props.onChange({ target: { value: "" } });
    assert.ok(Number.isNaN(changed.budget.resource_limits[0].amount));
  });
  await check("missing preparation option remains visible until explicitly removed", () => {
    let changed;
    const purpose = { ...demo.intent, future_builds: [{ skills: [], conditions: {}, feasibility: "owned", preparation_options: ["lost-quote"] }] };
    const tree = BuildEditor({ facts: demo.facts, intent: purpose, onFactsChange() {}, onIntentChange: x => { changed = x; } });
    button(tree, "移除失效准备方案").props.onClick();
    assert.deepEqual(changed.future_builds[0].preparation_options, []);
    assert.deepEqual(purpose.future_builds[0].preparation_options, ["lost-quote"]);
  });

  const equipmentStates = []; let equipmentCursor = 0;
  globalThis.equipmentFixture = { useState(value) {
    const index = equipmentCursor++;
    if (!(index in equipmentStates)) equipmentStates[index] = value;
    return [equipmentStates[index], next => { equipmentStates[index] = next; }];
  } };
  const equipmentTree = (facts, onChange) => { equipmentCursor = 0; return equipment.EquipmentEditor({ facts, onChange }); };
  await check("actual draft starts empty with explicit unreviewed build and slot", () => { assert.equal(fresh.context.game_id, "deskrawl"); assert.equal(fresh.context.game_build, "unknown"); assert.deepEqual(fresh.equipped_items, {}); assert.deepEqual(fresh.skills, []); assert.equal(fresh.inventory_coverage, "unknown"); assert.ok(fresh.unknowns.includes("build_not_reviewed") && fresh.unknowns.includes("current_slot_not_reviewed")); assert.ok(fresh.candidate_item.required_level === null); });
  await check("new equipment instances are distinct and do not mutate evidence inputs", () => { const refs = ["e1"]; const one = model.emptyItem(refs), two = model.emptyItem(refs); one.evidence_ids.push("e2"); assert.notEqual(one.instance_id, two.instance_id); assert.deepEqual(refs, ["e1"]); });
  await check("OCR only fills a field after explicit mapping with its source", () => { const item = structuredClone(demo.facts.candidate_item); const frozen = JSON.stringify(item); const next = equipment.mapItemField(item, { field: "vitality", value: -12.5, unit: "percent", ambiguous: false }, "capture-input"); assert.equal(next.affixes.at(-1).value, -12.5); assert.equal(next.affixes.at(-1).unit, "percent"); assert.deepEqual(next.affixes.at(-1).evidence_ids, ["capture-input"]); assert.equal(JSON.stringify(item), frozen); assert.deepEqual(next.effects, item.effects); });
  await check("ambiguous missing and unsupported OCR fields cannot be auto-applied", () => { for (const field of [{ field: "vitality", value: 65, unit: "points", ambiguous: true }, { field: "armor", value: null, unit: "points", ambiguous: false }, { field: "armor", value: 12, unit: null, ambiguous: false }, { field: "level", value: 2.5, unit: "level", ambiguous: false }, { field: "skill", value: 1, unit: "rank", ambiguous: false }]) assert.throws(() => equipment.mapItemField(fresh.candidate_item, field, "e1")); });
  await check("OCR level is an explicitly selected item requirement not character level", () => { const field = { field: "level", value: 20, unit: "level", ambiguous: false }; assert.throws(() => equipment.mapItemField(fresh.candidate_item, field, "e1")); const next = equipment.mapItemField(fresh.candidate_item, field, "e1", true); assert.equal(next.required_level, 20); assert.equal(fresh.character_level, 1); });
  await check("clearing an actual roll leaves it missing instead of recording zero", () => { let changed; const tree = equipment.ItemEditor({ item: demo.facts.candidate_item, onChange: x => { changed = x; } }); find(tree, n => n.type === "input" && n.props["aria-label"] === "词条实际数值").props.onChange({ target: { value: "" } }); assert.ok(Number.isNaN(changed.affixes[0].value)); assert.equal(demo.facts.candidate_item.affixes[0].value, 65); });
  await check("adding an affix requires an actual value and a matching identifier", () => { let changed; const tree = equipment.ItemEditor({ item: fresh.candidate_item, onChange: x => { changed = x; } }); button(tree, "添加词条").props.onClick(); assert.ok(Number.isNaN(changed.affixes[0].value)); assert.equal(changed.affixes[0].unit, "points"); });
  await check("embedded source editing preserves provenance and invalidates prior effect review", () => {
    const item = { ...model.emptyItem(["item-evidence"], "back"), unknowns: ["unidentified-affix"], embedded_items: [{ id: "existing-gem", effects: ["gem-effect"], actor: "hero", evidence_ids: ["older-evidence"] }] };
    const original = JSON.stringify(item); let changed;
    const embedded = component(equipment.ItemEditor({ item, onChange: next => { changed = next; } }), "SourceList");
    assert.deepEqual(embedded.props.evidenceIds, ["item-evidence"]);
    find(SourceList(embedded.props), n => n.type === "button" && Array.isArray(n.props.children) && n.props.children.join("") === "添加镶嵌物品").props.onClick();
    assert.equal(changed.embedded_items.length, 2);
    assert.deepEqual(changed.embedded_items[0], item.embedded_items[0]);
    assert.deepEqual(changed.embedded_items[1].evidence_ids, ["item-evidence"]);
    assert.deepEqual(changed.embedded_items[1].effects, []);
    assert.notEqual(changed.embedded_items[1].id, "existing-gem");
    assert.equal(changed.slot, "back");
    assert.deepEqual(changed.unknowns, ["unidentified-affix", "effects_not_reviewed"]);
    assert.equal(JSON.stringify(item), original);
    const edited = component(equipment.ItemEditor({ item: changed, onChange: next => { changed = next; } }), "SourceList");
    const rows = [...nodes(SourceList(edited.props))].filter(n => n.type.name === "SourceFields");
    rows[1].props.onChange({ ...changed.embedded_items[1], actor: "companion", effects: ["confirmed-gem-effect"] });
    assert.equal(changed.embedded_items[1].actor, "companion");
    assert.deepEqual(changed.embedded_items[1].effects, ["confirmed-gem-effect"]);
    const reviewed = equipment.ItemEditor({ item: changed, onChange: next => { changed = next; } });
    find(reviewed, n => n.type === "input" && n.props.type === "checkbox").props.onChange({ target: { checked: true } });
    assert.deepEqual(changed.unknowns, ["unidentified-affix"]);
    const removal = component(equipment.ItemEditor({ item: changed, onChange: next => { changed = next; } }), "SourceList");
    const removalRows = [...nodes(SourceList(removal.props))].filter(n => n.type.name === "SourceFields");
    removalRows[0].props.onDelete();
    assert.equal(changed.embedded_items.length, 1);
    assert.equal(changed.embedded_items[0].actor, "companion");
    assert.ok(changed.unknowns.includes("effects_not_reviewed"));
  });
  await check("build review only removes its own missing-input marker", () => { let changed; const tree = BuildEditor({ facts: fresh, intent: demo.intent, onFactsChange: x => { changed = x; }, onIntentChange: () => {} }); find(tree, n => n.type === "input" && n.props.type === "checkbox" && n.props.checked === false).props.onChange({ target: { checked: true } }); assert.ok(!changed.unknowns.includes("build_not_reviewed")); assert.ok(changed.unknowns.includes("current_slot_not_reviewed")); assert.equal(fresh.unknowns.length, 2); });
  await check("future goal changes increment intent without changing confirmed facts", () => { let changed; const before = JSON.stringify(fresh); const tree = BuildEditor({ facts: fresh, intent: demo.intent, onFactsChange: () => assert.fail("facts changed"), onIntentChange: x => { changed = x; } }); button(tree, "添加未来构筑").props.onClick(); assert.equal(changed.revision, demo.intent.revision + 1); assert.equal(changed.future_builds.length, 1); assert.equal(changed.future_builds[0].feasibility, ""); assert.equal(JSON.stringify(fresh), before); });
  await check("legacy inventory remains unrecorded until explicit review starts", () => {
    equipmentStates.length = 0;
    const legacy = structuredClone(fresh); delete legacy.inventory_items;
    const before = JSON.stringify(legacy); let changed;
    const tree = equipmentTree(legacy, value => { changed = value; });
    button(tree, "开始核对库存").props.onClick();
    assert.deepEqual(changed.inventory_items, []); assert.equal(changed.inventory_coverage, "partial");
    assert.deepEqual(changed.equipped_items, legacy.equipped_items); assert.deepEqual(changed.candidate_item, legacy.candidate_item);
    assert.equal(JSON.stringify(legacy), before);
    const coverage = BuildEditor({ facts: legacy, intent: demo.intent, onFactsChange: () => {}, onIntentChange: () => {} });
    const complete = find(coverage, node => node.type === "option" && node.props.value === "complete");
    assert.equal(complete.props.disabled, true);
  });
  await check("inventory entry preserves physical identity and edits invalidate complete coverage", () => {
    equipmentStates.length = 0;
    let changed; const original = JSON.stringify(fresh);
    let tree = equipmentTree(fresh, next => { changed = next; });
    find(tree, node => node.type === "select" && node.props["aria-label"] === "新增库存物品槽位").props.onChange({ target: { value: "back" } });
    tree = equipmentTree(fresh, next => { changed = next; });
    button(tree, "添加库存物品").props.onClick();
    const item = changed.inventory_items[0];
    assert.equal(item.slot, "back"); assert.notEqual(item.instance_id, fresh.candidate_item.instance_id);
    assert.deepEqual(item.evidence_ids, fresh.evidence_ids); assert.equal(changed.inventory_coverage, "partial");
    const complete = { ...changed, inventory_coverage: "complete" };
    const editor = find(equipmentTree(complete, next => { changed = next; }), node => node.type === equipment.ItemEditor && node.props.kind === "inventory");
    editor.props.onChange({ ...item, name: "Synthetic cloak", slot: "shoulders" });
    assert.equal(changed.inventory_items[0].instance_id, item.instance_id); assert.equal(changed.inventory_items[0].slot, "shoulders");
    assert.equal(changed.inventory_coverage, "partial"); assert.deepEqual(changed.equipped_items, fresh.equipped_items);
    tree = equipmentTree({ ...changed, inventory_coverage: "complete" }, next => { changed = next; });
    button(tree, "删除库存物品").props.onClick();
    assert.deepEqual(changed.inventory_items, []); assert.equal(changed.inventory_coverage, "partial");
    assert.equal(JSON.stringify(fresh), original);
  });
  await check("future equipment selection uses owned references with one item per slot", () => {
    const one = { ...model.emptyItem(fresh.evidence_ids, "body"), name: "First robe" };
    const two = { ...model.emptyItem(fresh.evidence_ids, "body"), name: "Second robe" };
    const cloak = { ...model.emptyItem(fresh.evidence_ids, "back"), name: "Cloak" };
    const facts = { ...fresh, inventory_items: [one, two, cloak] }; const original = JSON.stringify(facts);
    const purpose = { ...demo.intent, allowed_build_changes: ["equipment"], future_builds: [{ skills: [], conditions: {}, feasibility: "owned", equipment_items: [one.instance_id, cloak.instance_id] }] };
    let changed;
    const tree = BuildEditor({ facts, intent: purpose, onFactsChange: () => assert.fail("confirmed facts changed"), onIntentChange: next => { changed = next; } });
    find(tree, node => node.type === "input" && node.props["data-item-id"] === two.instance_id).props.onChange({ target: { checked: true } });
    assert.deepEqual(changed.future_builds[0].equipment_items, [cloak.instance_id, two.instance_id]);
    assert.equal(changed.revision, purpose.revision + 1); assert.equal(JSON.stringify(facts), original);
    assert.deepEqual(purpose.future_builds[0].equipment_items, [one.instance_id, cloak.instance_id]);
  });
  await check("deleted future references stay visible and can be removed without inventing inventory", () => {
    const purpose = { ...demo.intent, future_builds: [{ skills: [], conditions: {}, feasibility: "owned", equipment_items: ["missing-owned-item"] }] };
    let changed;
    const tree = BuildEditor({ facts: fresh, intent: purpose, onFactsChange: () => assert.fail("inventory changed"), onIntentChange: next => { changed = next; } });
    button(tree, "移除失效配套物品").props.onClick();
    assert.deepEqual(changed.future_builds[0].equipment_items, []); assert.equal(changed.revision, purpose.revision + 1);
    assert.deepEqual(fresh.inventory_items, []); assert.equal(fresh.inventory_coverage, "unknown");
  });
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
  await check("frozen future explanation shows named supporting equipment and declared feasibility", () => {
    const result = { evaluation_id: "future-render", retention: "candidate", comparison: { status: "no_known_change", scope_compatible: true, lost_capabilities: [], gained_capabilities: [], missing_requirements: [], equip_blockers: [], before: [], after: [] }, blockers: [], reasons: [{ kind: "future_use", capability: "archive_shield", actor: "hero", feasibility: "owned", future_build_index: 0, future_equipment: [{ instance_id: "saved-robe", slot: "body", name: "Synthetic robe" }], explanation: "Synthetic future combination", evidence_ids: ["fixture-spec"], input_evidence_ids: ["held-input"] }], pin: { context: demo.facts.context, profile_revision: 1, pack_version: "1.0.0", evaluator_version: "0.1.6", intent_revision: 2 } };
    const html = renderToStaticMarkup(createElement(EvaluationCard, { result, onReplay: () => {}, replaying: false, replayed: false }));
    assert.ok(html.includes("未来构筑 1") && html.includes("可行性声明：已拥有") && html.includes("胸部 · Synthetic robe"));
  });
  await check("explicit demo activation replaces only the requested draft and resets profile revision", async () => { await button(render(), "加载合成示例").props.onClick(); const tree = render(); assert.equal(component(tree, "EquipmentEditor").props.facts, demo.facts); assert.equal(component(tree, "ConfirmSnapshot").props.revision, 0); assert.ok(calls.includes("demo")); });
  for (const cleanup of cleanups) cleanup?.();
  console.log("Core UI fixture checks: " + checks.length + " passed; no browser or desktop input.");
} catch (error) { checks.push({ passed: false, error: error.message }); process.exitCode = 1; console.error(error); }
finally { await server.close(); if (reportPath) writeFileSync(reportPath, JSON.stringify({ scope: "Direct React handlers and static rendering; not GUI, scheduling, OCR or real-game acceptance.", passed: !process.exitCode, checks }, null, 2) + "\n", { flag: "wx" }); }
