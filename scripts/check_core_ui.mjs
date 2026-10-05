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
const button = (tree, text) => find(tree, n => n.type === "button" && [n.props.children].flat(Infinity).join("") === text);
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

  const fullResults = spawnSync(process.env.LOOTWEAVE_PYTHON || "python", ["-c", "import json; from tests.test_future_builds import full_case,full_result; f,p=full_case(); print(json.dumps({'facts':f,'intent':p,'result':full_result(f,p)}))"],
    { cwd: root, windowsHide: true, encoding: "utf8", timeout: 10000 });
  assert.ifError(fullResults.error); assert.equal(fullResults.status, 0, fullResults.stderr);
  const full = JSON.parse(fullResults.stdout);
  await check("complete future rendering separates affordable preparation from lost survival and rune dependencies", () => {
    const report = full.result.future_preparation[0];
    assert.equal(report.status, "feasible"); assert.equal(report.comparison.status, "mechanism_loss");
    for (const capability of ["resource_efficiency", "survival", "frost_cycle"])
      assert.ok(report.comparison.lost_capabilities.includes(capability));
    const html = renderToStaticMarkup(createElement(EvaluationCard, { result: full.result, onReplay() {}, replaying: false, replayed: false }));
    assert.ok(html.includes("满足已记录的准备条件") && html.includes("完整未来配置的机制变化"));
    assert.ok(html.includes("计划失去") && html.includes("角色 · 生存依赖") && html.includes("角色 · 符文循环"));
    assert.ok(html.includes("完整未来配置（计划，不会写入当前档案）"));
    assert.ok(html.includes("预计装备") && html.includes("预计条件"));
    assert.ok(html.includes("仆从等级 12") && html.includes("fixture-fire-bolt"));
    assert.deepEqual(full.facts.talents.length, 1); assert.deepEqual(full.facts.paragon.length, 1);
    assert.equal(full.facts.runes.length, 2);
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
  await check("all future source quote kinds begin unconfirmed without changing current sources", () => {
    for (const [kind, title, group, ranked] of [["skill", "技能", "skills", true], ["talent", "天赋", "talents", true],
      ["paragon", "巅峰", "paragon", true], ["rune", "符文", "runes", false],
      ["companion", "仆从", "companions", false], ["temporary_effect", "临时效果", "temporary_effects", false]]) {
      let changed;
      const before = JSON.stringify(demo.facts);
      button(equipment.PreparationOptionsEditor({ facts: demo.facts, onChange: x => { changed = x; } }), "添加" + title + "准备方案").props.onClick();
      const quote = changed.preparation_options[0];
      assert.equal(quote.kind, kind); assert.equal(quote.input, null); assert.equal(quote.costs, null);
      assert.equal(quote.requirements.unlock_state, "unknown"); assert.ok(quote.unknowns.includes("outcome_not_confirmed"));
      assert.equal(quote.result.rank, ranked ? 0 : undefined);
      assert.deepEqual(changed[group], demo.facts[group]); assert.equal(JSON.stringify(demo.facts), before);
    }
  });
  await check("explicit rune removal retains original input and invalidates projected review", () => {
    let facts = structuredClone(demo.facts);
    const original = JSON.stringify(facts);
    const render = () => equipment.PreparationOptionsEditor({ facts, onChange: x => { facts = x; } });
    button(render(), "添加符文准备方案").props.onClick();
    find(render(), n => n.props["aria-label"] === "方案目标符文").props.onChange({ target: { value: demo.facts.runes[0].id } });
    facts.preparation_options[0].unknowns = [];
    find(render(), n => n.props["aria-label"] === "计划移除符文").props.onChange({ target: { checked: true } });
    const quote = facts.preparation_options[0];
    assert.equal(quote.result, null); assert.deepEqual(quote.input, demo.facts.runes[0]);
    assert.ok(quote.unknowns.includes("outcome_not_confirmed")); assert.deepEqual(facts.runes, demo.facts.runes);
    find(render(), n => n.props["aria-label"] === "计划移除符文").props.onChange({ target: { checked: false } });
    assert.deepEqual(facts.preparation_options[0].result, demo.facts.runes[0]);
    assert.equal(JSON.stringify(demo.facts), original);
  });
  await check("each future source selection updates only its group and never current facts", () => {
    for (const [kind, group, ranked] of [["skill", "skills", true], ["talent", "talents", true],
      ["paragon", "paragon", true], ["rune", "runes", false], ["companion", "companions", false], ["temporary_effect", "temporary_effects", false]]) {
      const facts = structuredClone(demo.facts), id = "planned-" + kind;
      facts.preparation_options = [{ id: "quote-" + kind, kind, target_id: id, input: null,
        result: { id, actor: kind === "companion" ? "companion" : "hero", effects: [], evidence_ids: ["demo-input"], ...(ranked ? { rank: 3 } : {}) },
        context: facts.context, class_id: facts.class_id, costs: null, unknowns: ["outcome_not_confirmed"], evidence_ids: ["demo-input"],
        requirements: { required_level: null, max_rank: null, unlock_state: "unknown" } }];
      const before = JSON.stringify(facts);
      let purpose = { ...structuredClone(demo.intent), allowed_build_changes: [group], future_builds: [] };
      const render = () => BuildEditor({ facts, intent: purpose, onFactsChange: () => assert.fail("current facts changed"), onIntentChange: x => { purpose = x; } });
      button(render(), "添加未来构筑").props.onClick();
      const oldBuild = structuredClone(purpose.future_builds[0]);
      find(render(), n => n.props["data-preparation-id"] === "quote-" + kind).props.onChange({ target: { checked: true } });
      assert.ok(purpose.future_builds[0][group].includes(id));
      for (const other of ["skills", "talents", "paragon", "runes", "companions", "temporary_effects"].filter(key => key !== group))
        assert.deepEqual(purpose.future_builds[0][other], oldBuild[other]);
      find(render(), n => n.props["data-preparation-id"] === "quote-" + kind).props.onChange({ target: { checked: false } });
      assert.deepEqual(purpose.future_builds[0][group], oldBuild[group]); assert.equal(JSON.stringify(facts), before);
    }
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
    return [equipmentStates[index], next => { equipmentStates[index] = typeof next === "function" ? next(equipmentStates[index]) : next; }];
  } };
  const equipmentTree = (facts, onChange) => { equipmentCursor = 0; return equipment.EquipmentEditor({ facts, onChange }); };
  await check("actual draft starts empty with explicit unreviewed build and slot", () => { assert.equal(fresh.context.game_id, "deskrawl"); assert.equal(fresh.context.game_build, "unknown"); assert.deepEqual(fresh.equipped_items, {}); assert.deepEqual(fresh.skills, []); assert.equal(fresh.inventory_coverage, "unknown"); assert.ok(fresh.unknowns.includes("build_not_reviewed") && fresh.unknowns.includes("current_slot_not_reviewed")); assert.ok(fresh.candidate_item.required_level === null); });
  await check("new equipment instances are distinct and do not mutate evidence inputs", () => { const refs = ["e1"]; const one = model.emptyItem(refs), two = model.emptyItem(refs); one.evidence_ids.push("e2"); assert.notEqual(one.instance_id, two.instance_id); assert.deepEqual(refs, ["e1"]); });
  await check("OCR only fills a field after explicit mapping with its source", () => { const item = structuredClone(demo.facts.candidate_item); const frozen = JSON.stringify(item); const next = equipment.mapItemField(item, { field: "vitality", value: -12.5, unit: "percent", ambiguous: false }, "capture-input"); assert.equal(next.affixes.at(-1).value, -12.5); assert.equal(next.affixes.at(-1).unit, "percent"); assert.deepEqual(next.affixes.at(-1).evidence_ids, ["capture-input"]); assert.equal(JSON.stringify(item), frozen); assert.deepEqual(next.effects, item.effects); });
  await check("ambiguous missing and unsupported OCR fields cannot be auto-applied", () => { for (const field of [{ field: "vitality", value: 65, unit: "points", ambiguous: true }, { field: "armor", value: null, unit: "points", ambiguous: false }, { field: "armor", value: 12, unit: null, ambiguous: false }, { field: "level", value: 2.5, unit: "level", ambiguous: false }, { field: "skill", value: 1, unit: "rank", ambiguous: false }]) assert.throws(() => equipment.mapItemField(fresh.candidate_item, field, "e1")); });
  await check("OCR level is an explicitly selected item requirement not character level", () => { const field = { field: "level", value: 20, unit: "level", ambiguous: false }; assert.throws(() => equipment.mapItemField(fresh.candidate_item, field, "e1")); const next = equipment.mapItemField(fresh.candidate_item, field, "e1", true); assert.equal(next.required_level, 20); assert.equal(fresh.character_level, 1); });
  await check("OCR review keeps every raw line and unmatched proposal visible", () => {
    const fields = [{ field: "armor", value: 8, unit: "points", ambiguous: false, raw_text: "Armor 8 points" },
      { field: "vitality", value: 12, unit: null, ambiguous: true, raw_text: "Vitality 12" }];
    const rows = model.observationRows("  Item name  \r\nArmor 8 points\nStrength +18 Vitality 12\n\n", fields);
    assert.deepEqual(rows.map(row => row.rawText), ["  Item name  ", "Armor 8 points", "Strength +18 Vitality 12", "Vitality 12"]);
    assert.equal(rows[1].proposal, fields[0]); assert.equal(rows[3].proposal, fields[1]);
    assert.equal(model.observationRows("", [])[0].key, "empty");
  });
  await check("reviewed custom signed and zero rolls carry capture evidence without mutating other item facts", () => {
    const item = structuredClone(demo.facts.candidate_item), before = JSON.stringify(item);
    const next = model.mapReviewedItemFields(item, [{ kind: "affix", id: "strength", value: -18.25, unit: "points" },
      { kind: "affix", id: "custom-resist", value: 0, unit: "percent_points" }, { kind: "required_level", value: 12 }], "capture-only");
    assert.equal(next.required_level, 12);
    assert.deepEqual(next.affixes.slice(-2).map(row => [row.id, row.value, row.unit, row.evidence_ids]),
      [["strength", -18.25, "points", ["capture-only"]], ["custom-resist", 0, "percent_points", ["capture-only"]]]);
    assert.ok(next.evidence_ids.includes("capture-only"));
    assert.deepEqual(next.effects, item.effects); assert.deepEqual(next.embedded_items, item.embedded_items);
    assert.equal(JSON.stringify(item), before);
    assert.deepEqual(model.mapReviewedItemFields(item, [], "capture-only"), item);
  });
  await check("invalid or duplicate reviewed targets fail atomically and preserve prior candidate", () => {
    const before = JSON.stringify(fresh.candidate_item);
    const valid = { kind: "affix", id: "strength", value: 18, unit: "points" };
    for (const fields of [[valid, valid], [valid, { ...valid, id: "bad id" }], [{ ...valid, value: NaN }],
      [{ ...valid, unit: " " }], [{ ...valid, unit: "x".repeat(41) }], [{ kind: "required_level", value: 2.5 }],
      [{ kind: "required_level", value: 2 ** 53 }]]) assert.throws(() => model.mapReviewedItemFields(fresh.candidate_item, fields, "capture-only"));
    assert.equal(JSON.stringify(fresh.candidate_item), before);
  });
  const reviewHarness = (rawText, fields = [], onReviewed = () => true) => {
    equipmentStates.length = 0;
    return () => { equipmentCursor = 0; return equipment.ObservationFields({ rawText, fields, onReviewed }); };
  };
  const reviewControl = (render, name) => find(render(), n => n.props["aria-label"] === name);
  await check("all lines require an explicit decision and staged mapping applies only once", () => {
    const applied = [];
    const renderReview = reviewHarness("Strength +18\nFlavor text", [], rows => { applied.push(rows); return true; });
    const finish = () => button(renderReview(), "应用核对结果并完成");
    assert.equal(finish().props.disabled, true); finish().props.onClick(); assert.deepEqual(applied, []);
    reviewControl(renderReview, "第 1 行字段").props.onChange({ target: { value: "strength" } });
    reviewControl(renderReview, "第 1 行数值").props.onChange({ target: { value: "-18.25" } });
    reviewControl(renderReview, "第 1 行单位").props.onChange({ target: { value: "percent_points" } });
    const first = () => find(renderReview(), n => n.props["data-review-key"] === "line-0");
    button(first(), "核对后采用这一行").props.onClick();
    assert.equal(finish().props.disabled, true); assert.deepEqual(applied, []);
    const second = find(renderReview(), n => n.props["data-review-key"] === "line-1");
    button(second, "忽略这一行").props.onClick();
    assert.equal(finish().props.disabled, false); finish().props.onClick();
    assert.deepEqual(applied, [[{ kind: "affix", id: "strength", value: -18.25, unit: "percent_points" }]]);
    assert.equal(finish().props.disabled, true); finish().props.onClick(); assert.equal(applied.length, 1);
    assert.ok([...nodes(renderReview())].filter(n => n.type === "fieldset").every(n => n.props.disabled));
  });
  await check("edit after row acceptance returns it to pending and empty values never become zero", () => {
    const renderReview = reviewHarness("Armor 8 points", [{ field: "armor", value: 8, unit: "points", ambiguous: false, raw_text: "Armor 8 points" }]);
    button(renderReview(), "核对后采用这一行").props.onClick();
    assert.equal(button(renderReview(), "应用核对结果并完成").props.disabled, false);
    reviewControl(renderReview, "第 1 行数值").props.onChange({ target: { value: "" } });
    assert.equal(button(renderReview(), "核对后采用这一行").props.disabled, true);
    assert.equal(button(renderReview(), "应用核对结果并完成").props.disabled, true);
    button(renderReview(), "核对后采用这一行").props.onClick();
    assert.equal(button(renderReview(), "应用核对结果并完成").props.disabled, true);
  });
  await check("custom stat and unit require explicit values while duplicate targets stay blocked", () => {
    let accepted;
    const renderReview = reviewHarness("Cold resist\nDuplicate", [], rows => { accepted = rows; return true; });
    for (let i = 1; i <= 2; i++) {
      reviewControl(renderReview, "第 " + i + " 行字段").props.onChange({ target: { value: "custom" } });
      reviewControl(renderReview, "第 " + i + " 行自定义词条标识").props.onChange({ target: { value: "cold-resist" } });
      reviewControl(renderReview, "第 " + i + " 行数值").props.onChange({ target: { value: "0" } });
      reviewControl(renderReview, "第 " + i + " 行单位").props.onChange({ target: { value: "custom" } });
      reviewControl(renderReview, "第 " + i + " 行自定义单位").props.onChange({ target: { value: "resist-points" } });
      button(find(renderReview(), n => n.props["data-review-key"] === "line-" + (i - 1)), "核对后采用这一行").props.onClick();
    }
    assert.equal(button(renderReview(), "应用核对结果并完成").props.disabled, true);
    assert.ok([...nodes(renderReview())].some(n => n.type === "p" && n.props.children === "同一字段有多行，请合并或忽略重复行后再应用。"));
    button(find(renderReview(), n => n.props["data-review-key"] === "line-1"), "忽略这一行").props.onClick();
    button(renderReview(), "应用核对结果并完成").props.onClick();
    assert.deepEqual(accepted, [{ kind: "affix", id: "cold-resist", value: 0, unit: "resist-points" }]);
  });
  await check("ambiguous level needs explicit correction and all-ignored input never creates item facts", () => {
    let accepted;
    const renderReview = reviewHarness("Level 2.5", [{ field: "level", value: 2.5, unit: "level", ambiguous: true, raw_text: "Level 2.5" }], rows => { accepted = rows; return true; });
    assert.equal(button(renderReview(), "核对后采用这一行").props.disabled, true);
    assert.equal(reviewControl(renderReview, "第 1 行字段").props.value, "");
    reviewControl(renderReview, "第 1 行数值").props.onChange({ target: { value: "12" } });
    assert.equal(button(renderReview(), "核对后采用这一行").props.disabled, true);
    reviewControl(renderReview, "第 1 行字段").props.onChange({ target: { value: "required_level" } });
    button(renderReview(), "确认是穿戴要求，采用这一行").props.onClick(); button(renderReview(), "应用核对结果并完成").props.onClick();
    assert.deepEqual(accepted, [{ kind: "required_level", value: 12 }]);
    const empty = reviewHarness("", [], rows => { accepted = rows; return true; });
    assert.equal(button(empty(), "应用核对结果并完成").props.disabled, true);
    button(empty(), "忽略这一行").props.onClick(); button(empty(), "应用核对结果并完成").props.onClick();
    assert.deepEqual(accepted, []);
  });
  await check("batched changes keep the latest target value and unit before review", () => {
    let accepted;
    const renderReview = reviewHarness("Strength 18", [], rows => { accepted = rows; return true; });
    const tree = renderReview();
    find(tree, n => n.props["aria-label"] === "第 1 行字段").props.onChange({ target: { value: "strength" } });
    find(tree, n => n.props["aria-label"] === "第 1 行数值").props.onChange({ target: { value: "18" } });
    find(tree, n => n.props["aria-label"] === "第 1 行单位").props.onChange({ target: { value: "points" } });
    button(renderReview(), "核对后采用这一行").props.onClick(); button(renderReview(), "应用核对结果并完成").props.onClick();
    assert.deepEqual(accepted, [{ kind: "affix", id: "strength", value: 18, unit: "points" }]);
  });
  await check("reviewing an existing OCR percent unit preserves its stored spelling", () => {
    let accepted;
    const renderReview = reviewHarness("Vitality 12%", [{ field: "vitality", value: 12, unit: "%", ambiguous: false, raw_text: "Vitality 12%" }], rows => { accepted = rows; return true; });
    assert.equal(reviewControl(renderReview, "第 1 行单位").props.value, "custom");
    assert.equal(reviewControl(renderReview, "第 1 行自定义单位").props.value, "%");
    button(renderReview(), "核对后采用这一行").props.onClick(); button(renderReview(), "应用核对结果并完成").props.onClick();
    assert.deepEqual(accepted, [{ kind: "affix", id: "vitality", value: 12, unit: "%" }]);
  });
  await check("failed batch application preserves unlocked review for retry", () => {
    const renderReview = reviewHarness("Item name", [], () => false);
    button(renderReview(), "忽略这一行").props.onClick(); button(renderReview(), "应用核对结果并完成").props.onClick();
    assert.equal(button(renderReview(), "应用核对结果并完成").props.disabled, false);
  });
  equipmentStates.length = 0;
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
  await check("source selection opens the selected workflow and keeps API confirmation pending", () => {
    const source = value => find(render(), node => node.type === "input" && node.props.name === "input-source" && node.props.value === value);
    assert.equal(source("text").props.checked, true);
    source("api").props.onChange();
    assert.equal(source("api").props.checked, true);
    assert.ok(component(render(), "ImportLiveData"));
    assert.equal(component(render(), "ConfirmSnapshot").props.draftApplied, false);
    source("ocr").props.onChange();
    assert.equal(source("ocr").props.checked, true);
    assert.ok(component(render(), "CaptureObservationForm"));
  });
  await check("capture import retains its clock and leaves fields pending", () => { const capture = { observation_id: "fixture-capture", fields: [{ field: "vitality", value: 65, unit: "points", ambiguous: false }], raw_text: "Vitality +65", capture_context: { game_id: "deskrawl", captured_at_ms: 1767225600123 } }; component(render(), "CaptureObservationForm").props.onCaptured(capture); const facts = component(render(), "EquipmentEditor").props.facts; const evidence = facts.evidence.find(e => e.source_ref === "observation://fixture-capture"); assert.equal(evidence.captured_at, "2026-01-01T00:00:00.123Z"); assert.deepEqual(facts.candidate_item.affixes, []); assert.ok(facts.unknowns.includes("ocr_fields_not_mapped")); });
  await check("editing unknown markers cannot bypass capture review and successful mapping binds only the candidate", () => {
    const original = component(render(), "EquipmentEditor").props.facts;
    assert.equal(component(render(), "ConfirmSnapshot").props.captureReviewed, false);
    const withoutMarker = { ...original, unknowns: original.unknowns.filter(value => value !== "ocr_fields_not_mapped") };
    component(render(), "EquipmentEditor").props.onChange(withoutMarker);
    assert.equal(component(render(), "ConfirmSnapshot").props.captureReviewed, false);
    const review = component(render(), "ObservationFields");
    assert.equal(review.key, "fixture-capture"); assert.equal(review.props.rawText, "Vitality +65");
    const rows = [{ kind: "affix", id: "strength", value: -18, unit: "points" }, { kind: "affix", id: "custom-resist", value: 0, unit: "percent_points" }];
    assert.equal(review.props.onReviewed(rows), true);
    const saved = component(render(), "EquipmentEditor").props.facts;
    const id = saved.evidence.find(row => row.source_ref === "observation://fixture-capture").id;
    assert.deepEqual(saved.candidate_item.affixes.map(row => row.evidence_ids), [[id], [id]]);
    assert.ok(saved.candidate_item.evidence_ids.includes(id));
    assert.deepEqual(saved.equipped_items, original.equipped_items); assert.deepEqual(saved.skills, original.skills);
    assert.equal(saved.captured_at, original.captured_at); assert.deepEqual(saved.context, original.context);
    assert.equal(component(render(), "ConfirmSnapshot").props.captureReviewed, true);
    const nextCapture = { ...component(render(), "ConfirmSnapshot").props.capture, observation_id: "fixture-capture-next" };
    component(render(), "CaptureObservationForm").props.onCaptured(nextCapture);
    assert.equal(component(render(), "ObservationFields").key, "fixture-capture-next");
    assert.equal(component(render(), "ConfirmSnapshot").props.captureReviewed, false);
    assert.ok(component(render(), "EquipmentEditor").props.facts.unknowns.includes("ocr_fields_not_mapped"));
  });
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
