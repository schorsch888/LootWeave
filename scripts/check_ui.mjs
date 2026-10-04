// Browser regression against real local services, using only fictional inputs.
import assert from "node:assert/strict";
import { spawn, spawnSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(path.join(root, "frontend/package.json"));
const { chromium } = require("playwright");
const option = name => {
  const index = process.argv.indexOf(name);
  return index < 0 ? undefined : process.argv[index + 1];
};
const output = path.join(root, ".local/ui-check", randomUUID());
await mkdir(output, { recursive: true });
const python = option("--python") || process.env.LOOTWEAVE_PYTHON || "python";
// Seed one actual pre-fix result before services start; all reads/replays below use real HTTP.
const legacyEvaluationId = "legacy-hero-loss-masked-by-companion";
const seedCode = [
  "import json,sys",
  "from pathlib import Path",
  "from contracts import canonical,digest",
  "from services.evaluation.app import Evaluation",
  "from services.evaluation.domain import evaluate",
  "from storage import connect",
  "archive=json.loads(Path('fixtures/evaluation-0.1.1.json').read_text(encoding='utf-8'))",
  "case=archive['cases'][0]; inputs=case['inputs']",
  "result={'evaluation_id':case['evaluation_id'],**evaluate(inputs['profile'],inputs['knowledge'],inputs['intent'],evaluator_version=inputs['evaluator_version'])}",
  "assert digest(result)==case['result_hash']",
  "body={'request_id':case['evaluation_id'],'profile_id':inputs['profile']['profile_id'],'profile_revision':inputs['profile']['revision'],'pack_id':inputs['knowledge']['pack']['pack_id'],'pack_version':inputs['knowledge']['pack']['version'],'pack_hash':inputs['knowledge']['pack_hash'],'intent':inputs['intent']}",
  "app=Evaluation(Path(sys.argv[1]),None,None)",
  "with connect(app.database) as db: db.execute('INSERT INTO evaluations VALUES (?,?,?,?,?)',(case['evaluation_id'],digest(body),canonical(inputs),canonical(result),case['result_hash']))"
].join("\n");
const seeded = spawnSync(python, ["-c", seedCode, path.join(output, "state/evaluation")],
                         { cwd: root, windowsHide: true, timeout: 10000, encoding: "utf8" });
assert.equal(seeded.status, 0, "historical_fixture_seed_failed");
const child = spawn(python, ["runtime.py", "--stdio-control", "--no-browser", "--data-dir", path.join(output, "state")],
                    { cwd: root, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
let credential = "";
let browser;
let page;
let stage = "startup";
const results = [];
const simulatedNativeChecks = [];
const errors = [];
let failure = null;
let failureScreenshot = "not_requested";
const started = Date.now();
let runtimeUrl = "";
const wait = (event, emitter, timeout) => new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("timeout_" + event)), timeout);
  emitter.once(event, (...args) => { clearTimeout(timer); resolve(args); });
});
function waitForReady() {
  return new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error("readiness_timeout")), 20000);
  let buffer = "";
  child.stdout.on("data", chunk => {
    buffer += chunk.toString("utf8");
    if (buffer.length > 8192) { clearTimeout(timer); reject(new Error("invalid_readiness")); return; }
    if (buffer.includes("\n")) {
      clearTimeout(timer);
      try { resolve(JSON.parse(buffer.split("\n")[0])); }
      catch { reject(new Error("invalid_readiness")); }
    }
  });
  child.once("error", () => { clearTimeout(timer); reject(new Error("runtime_spawn_failed")); });
  child.once("exit", code => { clearTimeout(timer); reject(new Error("runtime_start_failed_" + code)); });
  });
}

async function check(text) {
  await page.getByText(text, { exact: false }).first().waitFor({ state: "visible" });
}
async function confirm(waitForSaved = true) {
  const checkbox = page.getByRole("checkbox", { name: "我已核对原文、实例词条和完整构筑，确认这些输入。" });
  await checkbox.and(page.locator(":enabled")).waitFor({ state: "visible" });
  await checkbox.focus();
  await page.keyboard.press("Space");
  assert.equal(await checkbox.isChecked(), true, "keyboard_confirmation_did_not_select_checkbox");
  const button = page.getByRole("button", { name: "确认并保存快照", exact: true });
  await button.focus();
  await page.keyboard.press("Enter");
  if (waitForSaved) await check("输入已确认，可以比较完整配置");
}
async function evaluate() {
  const button = page.getByRole("button", { name: "解释保留价值与换装变化 →", exact: true });
  await button.focus();
  await page.keyboard.press("Enter");
  await page.locator(".result").waitFor({ state: "visible" });
}
try {
  stage = "startup";
  const ready = await waitForReady();
  credential = ready.token;
  runtimeUrl = ready.url;
  stage = "browser";
  const launch = { headless: true };
  if (process.platform === "win32") launch.channel = "msedge";
  if (option("--browser-executable")) { delete launch.channel; launch.executablePath = option("--browser-executable"); }
  browser = await chromium.launch(launch);
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", error => errors.push(error.name));
  await page.goto(ready.url + "/#session=" + credential);
  await check("每次换装，都有依据");
  assert.equal(new URL(page.url()).hash, "");
  assert.equal(new URL(page.url()).search, "");
  // Real input is the default; this regression deliberately selects fictional data.
  await page.getByRole("button", { name: "加载合成示例", exact: true }).click();
  await check("当前使用合成示例");
  await page.locator("summary").filter({ hasText: "路线试验与获取记录" }).click();
  stage = "confirmation";
  assert.equal(await page.getByRole("button", { name: "解释保留价值与换装变化 →" }).isEnabled(), false);
  await page.locator("summary").filter({ hasText: "查看或编辑完整构筑数据" }).click();
  let releaseConfirmation;
  let signalConfirmationPaused;
  const confirmationPaused = new Promise(resolve => { signalConfirmationPaused = resolve; });
  const confirmationGate = new Promise(resolve => { releaseConfirmation = resolve; });
  await page.route("**/api/profile/confirmations", async route => {
    signalConfirmationPaused();
    await confirmationGate;
    await route.continue();
  }, { times: 1 });
  await confirm(false);
  await confirmationPaused;
  const draftControls = page.locator("fieldset.draft-controls").first().locator("input, select, textarea, button");
  const draftControlCount = await draftControls.count();
  assert(draftControlCount > 0, "draft_controls_not_found");
  try {
    const states = await draftControls.evaluateAll(controls => controls.map(control => control.matches(":disabled")));
    assert.equal(states.length, draftControlCount, "draft_controls_changed_during_confirmation");
    assert(states.every(Boolean), "draft_control_editable_during_confirmation");
  } finally {
    releaseConfirmation();
  }
  await check("输入已确认，可以比较完整配置");
  assert.equal(await page.getByLabel("游戏范围", { exact: true }).isDisabled(), false);
  assert.equal(await page.getByLabel("完整构筑数据", { exact: true }).isDisabled(), false);
  assert.equal(await page.getByRole("button", { name: "应用构筑修改", exact: true }).isDisabled(), false);
  await page.locator("summary").filter({ hasText: "查看或编辑完整构筑数据" }).click();
  results.push("keyboard_confirmation_and_session_fragment_removal");
  results.push("draft_controls_lock_until_confirmation_finishes");

  stage = "replacement";
  const initialEvaluationRequest = page.waitForRequest("**/api/evaluation/evaluations");
  await evaluate();
  const evaluationBody = (await initialEvaluationRequest).postDataJSON();
  await check("换装会丢失机制");
  await check("两件套防护");
  await check("法力循环");
  results.push("whole_build_replacement_detects_core_mechanism_loss");

  const unknownGoalId = "unknown-goal-" + randomUUID();
  const unknownGoalBody = structuredClone(evaluationBody);
  unknownGoalBody.request_id = unknownGoalId;
  unknownGoalBody.intent.revision += 1;
  unknownGoalBody.intent.required_capabilities = ["unmapped-resource-cycle"];
  const unknownGoalResponse = await page.request.post(runtimeUrl + "/api/evaluation/evaluations", {
    headers: { Authorization: "Bearer " + credential }, data: unknownGoalBody
  });
  assert.equal(unknownGoalResponse.status(), 200, "unknown_goal_request_failed");
  const unknownGoalResult = await unknownGoalResponse.json();
  assert.equal(unknownGoalResult.retention, "needs_confirmation");
  assert.equal(unknownGoalResult.comparison.scope_compatible, true);
  assert.deepEqual(unknownGoalResult.comparison.missing_requirements, []);

  const catalogResponse = await page.request.get(runtimeUrl + "/api/knowledge/packs", {
    headers: { Authorization: "Bearer " + credential }
  });
  assert.equal(catalogResponse.status(), 200, "scope_fixture_catalog_failed");
  const researchPack = (await catalogResponse.json()).packs.find(pack => pack.execution_policy === "research_only");
  assert(researchPack, "scope_fixture_pack_missing");
  const incompatibleScopeId = "incompatible-scope-" + randomUUID();
  const incompatibleBody = { ...evaluationBody, request_id: incompatibleScopeId,
    pack_id: researchPack.pack_id, pack_version: researchPack.version, pack_hash: researchPack.pack_hash };
  const incompatibleResponse = await page.request.post(runtimeUrl + "/api/evaluation/evaluations", {
    headers: { Authorization: "Bearer " + credential }, data: incompatibleBody
  });
  assert.equal(incompatibleResponse.status(), 200, "incompatible_scope_request_failed");
  const incompatibleResult = await incompatibleResponse.json();
  assert.equal(incompatibleResult.comparison.scope_compatible, false);
  assert.deepEqual(incompatibleResult.comparison.before, []);
  assert.deepEqual(incompatibleResult.comparison.after, []);
  assert.deepEqual(incompatibleResult.comparison.missing_requirements, []);

  stage = "replay";
  await page.getByRole("button", { name: "回放验证", exact: true }).click();
  await check("回放一致");
  results.push("frozen_replay_matches");

  stage = "eligibility";
  await page.getByRole("button", { name: "核对当前条件", exact: true }).click();
  await check("条件未知");
  results.push("unknown_source_access_is_preserved");

  stage = "sampling";
  await page.locator("summary").filter({ hasText: "记录一次人工观察样本" }).click();
  await page.getByLabel("目标事件", { exact: true }).fill("fictional-item-observed");
  await page.getByLabel("一次尝试的单位", { exact: true }).fill("one fictional chest");
  await page.getByLabel("观察到成功次数", { exact: true }).fill("4");
  assert.equal(await page.getByRole("button", { name: "提交完整观察样本", exact: true }).isEnabled(), false);
  await page.getByRole("checkbox", { name: "每次尝试及其结果都已完整记录" }).check();
  await page.getByRole("checkbox", { name: "观察期间版本及设置保持不变" }).check();
  await page.getByRole("button", { name: "提交完整观察样本", exact: true }).click();
  await check("估计比例：4.0%");
  await check("观察到的成功次数：4");
  results.push("observed_samples_require_complete_coverage_and_show_uncertainty");

  stage = "trials";
  await page.getByRole("checkbox", { name: "本次构筑和加成保持一致，没有跨越角色/巅峰经验转换。" }).check();
  await page.getByRole("button", { name: "记录试验并比较", exact: true }).click();
  await check("已测候选中最高");
  await check("建议复测");
  results.push("measured_routes_use_actual_xp_and_complete_time");

  const routePanel = page.locator("section.panel").filter({
    has: page.getByRole("heading", { name: "用实际试验比较练级路线", exact: true })
  });
  const trialConsent = routePanel.getByRole("checkbox", {
    name: "本次构筑和加成保持一致，没有跨越角色/巅峰经验转换。"
  });
  const trialButton = routePanel.getByRole("button", { name: "记录试验并比较", exact: true });
  const levelStart = routePanel.getByLabel("试验起始等级", { exact: true });
  const levelEnd = routePanel.getByLabel("试验结束等级", { exact: true });
  const trialRow = map => routePanel.getByRole("row").filter({ hasText: map + " / normal" });

  stage = "trial_level_range";
  assert.equal(await levelStart.inputValue(), "15");
  assert.equal(await levelEnd.inputValue(), "15");
  await levelEnd.fill("14");
  assert.equal(await trialConsent.isChecked(), false, "trial_consent_survives_scope_change");
  assert.equal(await routePanel.getByRole("table").count(), 0, "old_ranking_survives_scope_change");
  await trialConsent.check();
  assert.equal(await trialButton.isDisabled(), true, "inverted_trial_range_accepted");
  await levelEnd.fill("16");
  await routePanel.getByLabel("实际累计经验", { exact: true }).fill("300");
  await routePanel.getByLabel("完整耗时（秒）", { exact: true }).fill("120");
  await trialConsent.check();
  await trialButton.click();
  await routePanel.getByText("比较范围：角色等级 15 → 16", { exact: true }).waitFor();
  assert.equal(await trialRow("示例地图").getByRole("cell").nth(1).innerText(), "1",
    "cross_level_trial_pooled_with_previous_range");
  assert.equal(await trialRow("示例地图").getByRole("cell").nth(2).innerText(), "150.00");
  await routePanel.getByText("已排除 1 条范围不一致的历史试验。", { exact: true }).waitFor();
  await routePanel.getByLabel("经验加成记录", { exact: true }).fill("人工核对不同经验加成");
  assert.equal(await trialConsent.isChecked(), false, "trial_consent_survives_bonus_change");
  assert.equal(await routePanel.getByRole("table").count(), 0, "old_ranking_survives_bonus_change");
  await routePanel.getByLabel("经验加成记录", { exact: true }).fill("已确认无额外经验加成");
  results.push("actual_level_ranges_exclude_incomparable_history_and_clear_stale_rankings");

  stage = "trial_paragon_range";
  await routePanel.getByLabel("经验类型").selectOption("paragon");
  assert.equal(await levelStart.inputValue(), "", "character_start_level_reused_for_paragon");
  assert.equal(await levelEnd.inputValue(), "", "character_end_level_reused_for_paragon");
  await trialConsent.check();
  assert.equal(await trialButton.isDisabled(), true, "missing_paragon_levels_accepted");
  await levelStart.fill("-1");
  await levelEnd.fill("1");
  await trialConsent.check();
  assert.equal(await trialButton.isDisabled(), true, "negative_paragon_level_accepted");
  await levelStart.fill("0");
  await trialConsent.check();
  await trialButton.click();
  await routePanel.getByText("比较范围：巅峰等级 0 → 1", { exact: true }).waitFor();
  assert.equal(await trialRow("示例地图").getByRole("cell").nth(1).innerText(), "1",
    "paragon_trial_pooled_with_character_trials");
  await routePanel.getByText("已排除 2 条范围不一致的历史试验。", { exact: true }).waitFor();
  results.push("paragon_ranges_require_independent_levels_and_never_pool_character_xp");

  stage = "trial_comparison_retry";
  await routePanel.getByLabel("经验类型").selectOption("character");
  await levelEnd.fill("17");
  await routePanel.getByLabel("地图", { exact: true }).fill("重试试验地图");
  await routePanel.getByLabel("实际累计经验", { exact: true }).fill("");
  await routePanel.getByLabel("完整耗时（秒）", { exact: true }).fill("90");
  await trialConsent.check();
  assert.equal(await trialButton.isDisabled(), true, "blank_actual_xp_assumed_zero");
  await routePanel.getByLabel("实际累计经验", { exact: true }).fill("180");
  await trialConsent.check();
  let releaseTrialSave;
  let signalTrialSavePaused;
  const trialSavePaused = new Promise(resolve => { signalTrialSavePaused = resolve; });
  const trialSaveGate = new Promise(resolve => { releaseTrialSave = resolve; });
  const trialRequests = [];
  const interceptTrial = async route => {
    trialRequests.push(route.request().postDataJSON());
    if (trialRequests.length === 1) {
      signalTrialSavePaused();
      await trialSaveGate;
    }
    await route.continue();
  };
  await page.route("**/api/planning/trials", interceptTrial);
  await page.route("**/api/planning/routes/compare", route => route.fulfill({
    status: 503, contentType: "application/json", body: JSON.stringify({ error: "service_unavailable" })
  }), { times: 1 });
  await trialButton.click();
  await trialSavePaused;
  try {
    const controls = routePanel.locator("fieldset input, fieldset select, fieldset button");
    assert((await controls.count()) > 0, "trial_controls_missing");
    const states = await controls.evaluateAll(items => items.map(control => control.matches(":disabled")));
    assert(states.length > 0, "trial_controls_missing");
    assert(states.every(Boolean), "trial_control_editable_during_save");
  } finally {
    releaseTrialSave();
  }
  const trialError = "服务暂时不可用，已保存的快照仍会保留。";
  await page.getByText(trialError, { exact: true }).waitFor();
  assert.equal(await routePanel.getByRole("table").count(), 0, "failed_comparison_shows_old_ranking");
  await trialButton.click();
  await routePanel.getByText("比较范围：角色等级 15 → 17", { exact: true }).waitFor();
  assert.equal(trialRequests.length, 2, "trial_retry_request_missing");
  assert.deepEqual(trialRequests[0], trialRequests[1], "trial_retry_generated_new_identity_or_measurement");
  assert.equal(await trialRow("重试试验地图").getByRole("cell").nth(1).innerText(), "1",
    "saved_trial_counted_twice_after_comparison_failure");
  assert.equal(await trialRow("重试试验地图").getByRole("cell").nth(2).innerText(), "120.00");
  assert.equal(await page.getByText(trialError, { exact: true }).count(), 0, "successful_retry_keeps_old_error");
  await page.unroute("**/api/planning/trials", interceptTrial);
  results.push("trial_controls_lock_and_saved_trial_retries_without_duplicate_counting");

  stage = "actor_comparison";
  const ownerFacts = JSON.parse(await readFile(path.join(root, "fixtures/demo.json"), "utf8")).facts;
  ownerFacts.companions.forEach(source => { source.effects = []; });
  ownerFacts.equipped_items.weapon.embedded_items.push({
    id: "companion-anchor", actor: "companion", effects: ["fixture-companion-support"],
    evidence_ids: ["demo-input"]
  });
  ownerFacts.candidate_item = structuredClone(ownerFacts.equipped_items.weapon);
  ownerFacts.candidate_item.instance_id = "same-hero-mechanisms-candidate";
  ownerFacts.candidate_item.embedded_items = [];
  await page.locator("summary").filter({ hasText: "查看或编辑完整构筑数据" }).click();
  await page.getByLabel("完整构筑数据", { exact: true }).fill(JSON.stringify(ownerFacts, null, 2));
  await page.getByRole("button", { name: "应用构筑修改", exact: true }).click();
  await confirm();
  await evaluate();
  const lostPanel = page.locator(".result .delta-grid > div").filter({
    has: page.getByRole("heading", { name: "换装失去", exact: true })
  });
  await lostPanel.getByText("仆从 · 仆从支持", { exact: true }).waitFor({ state: "visible" });
  assert.equal(await lostPanel.getByText("角色 · 仆从支持", { exact: true }).count(), 0,
    "companion_loss_presented_as_hero_loss");
  await check("评估器 0.1.5");
  await page.locator(".result").screenshot({ path: path.join(output, "actor-comparison.png") });
  results.push("actual_companion_loss_keeps_owner_in_complete_build_and_ui");
  await page.locator("summary").filter({ hasText: "查看或编辑完整构筑数据" }).click();

  stage = "unknown_conditions";
  await page.getByLabel("法力成为瓶颈").selectOption("unknown");
  assert.equal(await page.getByRole("button", { name: "解释保留价值与换装变化 →" }).isEnabled(), false);
  await confirm();
  await evaluate();
  await check("需要补充确认");
  await check("比较受阻");
  results.push("edited_unknown_condition_blocks_definitive_evaluation");

  stage = "unapplied_draft";
  await page.locator("summary").filter({ hasText: "查看或编辑完整构筑数据" }).click();
  await page.getByLabel("完整构筑数据", { exact: true }).fill("{}");
  assert.equal(await page.getByRole("checkbox", { name: "我已核对原文、实例词条和完整构筑，确认这些输入。" }).isEnabled(), false);
  await page.getByRole("button", { name: "应用构筑修改", exact: true }).click();
  await check("构筑数据格式不完整");
  results.push("invalid_or_unapplied_json_cannot_overwrite_confirmed_facts");

  stage = "history";
  await page.reload();
  await check("每次换装，都有依据");
  await page.locator("summary").filter({ hasText: "查看历史冻结评估" }).click();
  await page.locator("article.reason").filter({ hasText: "评估器版本：0.1.5" })
    .getByRole("button", { name: "查看这份冻结结果", exact: true }).last().click();
  await check("正在查看保存的冻结输入及其规则版本");
  await check("换装会丢失机制");
  await page.getByRole("button", { name: "回放验证", exact: true }).click();
  await check("回放一致");
  results.push("historical_results_survive_refresh_and_replay_with_original_versions");
  await page.screenshot({ path: path.join(output, "desktop.png"), fullPage: true });

  stage = "unknown_goal_history";
  await page.locator("article.reason").filter({ hasText: "评估 ID：" + unknownGoalId })
    .getByRole("button", { name: "查看这份冻结结果", exact: true }).click();
  await check("需要补充确认");
  await check("该版本知识包尚未收录所需机制：unmapped-resource-cycle");
  assert.equal(await page.locator(".result .warning").filter({ hasText: "unmapped-resource-cycle" }).count(), 0,
    "unmapped_goal_presented_as_known_missing_mechanism");
  await page.getByRole("button", { name: "回放验证", exact: true }).click();
  await check("回放一致");
  results.push("unknown_goal_blocks_verdict_without_claiming_known_absence");

  stage = "incompatible_scope_history";
  await page.locator("article.reason").filter({ hasText: "评估 ID：" + incompatibleScopeId })
    .getByRole("button", { name: "查看这份冻结结果", exact: true }).click();
  await check("游戏机制尚未验证，或范围、版本不匹配；物品字段差异仍可查看。");
  assert.equal(await page.locator(".result .delta-grid").count(), 0,
    "incompatible_scope_shows_mechanism_delta_claims");
  await page.getByRole("button", { name: "回放验证", exact: true }).click();
  await check("回放一致");
  results.push("incompatible_pack_has_no_mechanism_conclusion_in_actual_ui");
  stage = "legacy_history";
  const legacyArticle = page.locator("article.reason").filter({
    hasText: "评估 ID：" + legacyEvaluationId
  });
  await legacyArticle.getByRole("button", { name: "查看这份冻结结果", exact: true }).click();
  await check("评估器 0.1.1");
  await check("未发现已知机制变化");
  assert.equal(await page.locator(".result .delta-grid > div").first().getByRole("list").count(), 0,
    "legacy_result_was_reinterpreted_with_current_actor_projection");
  await page.getByRole("button", { name: "回放验证", exact: true }).click();
  await check("回放一致");
  results.push("pre_fix_0_1_1_history_uses_original_shape_and_exact_http_replay");


  stage = "responsive";
  await page.setViewportSize({ width: 390, height: 844 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  assert(overflow <= 1, "mobile_horizontal_overflow_" + overflow);
  await page.screenshot({ path: path.join(output, "mobile.png"), fullPage: true });
  assert.equal(errors.length, 0);
  results.push("responsive_layout_and_no_uncaught_browser_errors");

  stage = "deskrawl_simulated_native_ipc";
  await page.getByRole("button", { name: "加载合成示例", exact: true }).click();
  await check("当前使用合成示例");
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.locator("summary").filter({ hasText: "从截图识别装备字段" }).click();
  await page.locator("summary").filter({ hasText: "从屏幕区域读取" }).click();
  const genericCapture = page.getByRole("button", { name: "捕获所选区域并读取", exact: true });
  assert.equal(await genericCapture.count(), 1, "generic_capture_mode_missing_for_other_scopes");
  const genericSource = page.locator("label").filter({ hasText: "捕获来源" }).locator("select");
  assert.equal(await genericSource.count(), 1,
    "generic_source_selector_missing_for_other_scopes");
  const rawTextField = page.getByLabel("原始文本", { exact: true });
  const originalText = await rawTextField.inputValue();
  await page.getByLabel("游戏范围", { exact: true }).fill("deskrawl");
  assert.equal(await page.locator("label").filter({ hasText: "捕获来源" }).locator("select").count(), 0,
    "deskrawl_exposes_generic_source_selector");
  const windowCapture = page.getByRole("button", { name: "捕获所选游戏窗口区域并读取", exact: true });
  assert.equal(await windowCapture.count(), 1, "deskrawl_window_capture_button_missing");

  let ocrRequests = 0;
  await page.route("**/api/ocr/regions", async route => {
    ocrRequests += 1;
    await route.continue();
  });
  await page.evaluate(() => {
    globalThis.isTauri = true;
    const state = { scenario: "not_running", detectionCalls: 0, captureCalls: 0 };
    window.__deskrawlMockState = state;
    const clientBounds = { x: 100, y: 50, width: 1000, height: 700 };
    window.__TAURI_INTERNALS__ = {
      invoke: async (command, args) => {
        if (!args || typeof args.sessionToken !== "string" || !args.sessionToken) {
          throw new Error("mock_ipc_session_missing");
        }
        if (command === "detect_deskrawl_windows") {
          if (Object.keys(args).length !== 1) throw new Error("mock_ipc_detection_arguments_invalid");
          state.detectionCalls += 1;
          if (state.scenario === "delayed_not_running") {
            await new Promise(resolve => { state.releaseDetection = resolve; });
            state.delayedDetectionFinished = true;
            return { game_id: "deskrawl", executable: "Deskrawl.exe", status: "not_running",
              process_count: 0, unavailable_processes: 0, version_verified: false, windows: [] };
          }
          if (state.scenario === "not_running") {
            return { game_id: "deskrawl", executable: "Deskrawl.exe", status: "not_running",
              process_count: 0, unavailable_processes: 0, version_verified: false, windows: [] };
          }
          return { game_id: "deskrawl", executable: "Deskrawl.exe", status: "running",
            process_count: 2, unavailable_processes: 0, version_verified: false,
            windows: [
              { binding_id: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", index: 1, status: "background",
                client_bounds: clientBounds, can_select: true },
              { binding_id: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb", index: 2, status: "minimized",
                client_bounds: clientBounds, can_select: false }
            ] };
        }
        if (command === "capture_deskrawl_region") {
          state.captureCalls += 1;
          if (state.scenario === "not_foreground") throw new Error("game_window_not_foreground");
          if (state.scenario !== "success") throw new Error("unexpected_mock_capture_scenario");
          if (Object.keys(args).sort().join(",") !== "bindingId,height,sessionToken,width,x,y") {
            throw new Error("mock_ipc_capture_arguments_invalid");
          }
          const width = args.width;
          const height = args.height;
          const rowBytes = width * 4;
          const bytes = new Uint8Array(54 + rowBytes * height);
          const view = new DataView(bytes.buffer);
          bytes[0] = 0x42; bytes[1] = 0x4d;
          view.setUint32(2, bytes.length, true);
          view.setUint32(10, 54, true);
          view.setUint32(14, 40, true);
          view.setInt32(18, width, true);
          view.setInt32(22, height, true);
          view.setUint16(26, 1, true);
          view.setUint16(28, 32, true);
          view.setUint32(30, 0, true);
          view.setUint32(34, rowBytes * height, true);
          let binary = "";
          for (const byte of bytes) binary += String.fromCharCode(byte);
          return {
            image_base64: btoa(binary),
            bounds: { x: clientBounds.x + args.x, y: clientBounds.y + args.y, width, height },
            capture_context: {
              format_version: 1, game_id: "deskrawl", executable: "Deskrawl.exe",
              window_binding: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", client_bounds: clientBounds,
              relative_bounds: { x: args.x, y: args.y, width, height },
              verification: "foreground_before_and_after", captured_at_ms: Date.now(),
              game_version: "unknown", game_build: "unknown"
            }
          };
        }
        throw new Error("unexpected_mock_native_command");
      }
    };
  });

  assert.equal(await windowCapture.isDisabled(), true, "capture_enabled_before_detection_or_selection");
  assert.equal(await rawTextField.isEnabled(), true,
    "manual_text_entry_disabled_in_deskrawl_mode");
  assert.equal(await rawTextField.inputValue(), originalText,
    "deskrawl_scope_changed_existing_text");
  await page.getByRole("button", { name: "检测 / 重新检测 Deskrawl 窗口", exact: true }).click();
  await check("未检测到 Deskrawl.exe 正在运行");
  assert.equal(await windowCapture.isDisabled(), true, "capture_enabled_when_deskrawl_is_not_running");
  assert.equal(await rawTextField.inputValue(), originalText,
    "not_running_detection_changed_original_text");
  simulatedNativeChecks.push("deskrawl_scope_requires_explicit_window_and_not_running_keeps_text_usable");

  await page.evaluate(() => { window.__deskrawlMockState.scenario = "multiple"; });
  await page.getByRole("button", { name: "检测 / 重新检测 Deskrawl 窗口", exact: true }).click();
  await check("进程数：2");
  const windowSelector = page.locator("label").filter({ hasText: "选择 Deskrawl 窗口（不会自动选择）" }).locator("select");
  assert.equal(await windowSelector.inputValue(), "", "first_window_was_silently_selected");
  const backgroundOption = windowSelector.locator("option").filter({ hasText: "窗口 1" });
  const minimizedOption = windowSelector.locator("option").filter({ hasText: "窗口 2" });
  assert.equal(await backgroundOption.count(), 1, "background_window_option_missing");
  assert.equal(await minimizedOption.count(), 1, "minimized_window_option_missing");
  const optionState = await windowSelector.locator("option").evaluateAll(options => options.map(option => ({
    text: option.textContent, disabled: option.disabled, value: option.value,
  })));
  assert.equal(await minimizedOption.evaluate(option => option.disabled), true,
    "minimized_window_option_should_be_disabled " + JSON.stringify(optionState));
  assert.equal(await backgroundOption.evaluate(option => option.disabled), false,
    "background_window_should_be_selectable");
  assert.equal(await windowCapture.isDisabled(), true, "capture_enabled_without_explicit_window_choice");
  await windowSelector.selectOption("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  assert.equal(await windowCapture.isEnabled(), true, "valid_selected_window_did_not_enable_capture");
  const regionX = page.getByLabel("客户区左侧坐标（物理像素）", { exact: true });
  const regionWidth = page.getByLabel("区域宽度（物理像素）", { exact: true });
  await regionX.fill("201");
  assert.equal(await windowCapture.isDisabled(), true, "out_of_client_region_did_not_disable_capture");
  await regionX.fill("0");
  await regionWidth.fill("32");
  await page.getByLabel("区域高度（物理像素）", { exact: true }).fill("24");
  assert.equal(await windowCapture.isEnabled(), true, "valid_relative_physical_region_not_enabled");

  await page.evaluate(() => { window.__deskrawlMockState.scenario = "not_foreground"; });
  const ocrBeforeRejectedCapture = ocrRequests;
  await windowCapture.click();
  await page.getByRole("status").filter({ hasText: "3 秒后捕获" }).waitFor({ state: "visible" });
  assert.equal(await page.getByLabel("游戏范围", { exact: true }).isDisabled(), true,
    "draft_scope_editable_during_window_capture");
  assert.equal(await rawTextField.isDisabled(), true,
    "manual_text_editable_during_window_capture");
  await check("Deskrawl 不是当前前台窗口");
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")]
      .find(item => item.textContent.includes("捕获所选游戏窗口区域并读取"));
    return button && !button.disabled;
  });
  assert.equal(ocrRequests, ocrBeforeRejectedCapture, "rejected_native_capture_reached_ocr");
  assert.equal(await rawTextField.inputValue(), originalText,
    "rejected_native_capture_changed_original_text");
  simulatedNativeChecks.push("deskrawl_relative_region_gating_busy_lock_and_foreground_rejection");

  await regionWidth.fill("800");
  await page.evaluate(() => { window.__deskrawlMockState.scenario = "success"; });
  const ocrRequest = page.waitForRequest("**/api/ocr/regions");
  await windowCapture.click();
  await page.getByRole("status").filter({ hasText: "3 秒后捕获" }).waitFor({ state: "visible" });
  const requestedOcr = await ocrRequest;
  assert.equal(new URL(requestedOcr.url()).pathname, "/api/ocr/regions");
  await check("已保留原始区域与识别原文；字段仍需逐项核对。");
  assert.equal(ocrRequests, ocrBeforeRejectedCapture + 1, "successful_native_mock_did_not_use_real_ocr_http");
  assert.equal(await page.getByLabel("游戏范围", { exact: true }).inputValue(), "deskrawl",
    "capture_context_changed_game_scope");
  assert.equal(await page.getByLabel("构建版本", { exact: true }).inputValue(), "1",
    "unknown_capture_version_overwrote_build");
  assert.equal(await page.getByLabel("角色等级", { exact: true }).inputValue(), "15",
    "ocr_capture_automatically_changed_character_level");
  assert.equal(await page.locator(".affix-list input").first().inputValue(), "65",
    "ocr_capture_automatically_changed_item_facts");
  assert.equal(await page.getByRole("checkbox", {
    name: "我已核对原文、实例词条和完整构筑，确认这些输入。"
  }).isChecked(), false, "synthetic_ocr_was_implicitly_confirmed");
  assert.equal(await page.getByRole("button", { name: "解释保留价值与换装变化 →" }).isEnabled(), false,
    "evaluation_enabled_before_manual_capture_confirmation");
  simulatedNativeChecks.push("deskrawl_synthetic_capture_uses_real_ocr_but_keeps_facts_unconfirmed");

  stage = "capture_original_review";
  const capturePreview = page.getByRole("img", { name: "本次捕获的原始区域", exact: true });
  await capturePreview.waitFor({ state: "visible" });
  const submittedImage = requestedOcr.postDataJSON();
  assert.equal(await capturePreview.getAttribute("src"), "data:image/bmp;base64," + submittedImage.image_base64,
    "preview_does_not_show_original_submitted_region");
  await page.waitForFunction(() => document.querySelector(".capture-review img")?.naturalWidth === 800);
  assert.equal(await capturePreview.evaluate(image => image.naturalHeight), 24);
  const acceptedOcr = await (await requestedOcr.response()).json();
  const immutableOcrText = page.locator(".capture-review pre");
  assert.equal(await immutableOcrText.innerText(),
    acceptedOcr.raw_text || "未识别到可用文字，请手动填写原始文本。");
  await page.setViewportSize({ width: 390, height: 844 });
  const imageViewport = page.getByRole("region", { name: "原始区域查看区", exact: true });
  const viewportWidths = await imageViewport.evaluate(element => ({
    visible: element.clientWidth, full: element.scrollWidth,
    outerOverflow: document.documentElement.scrollWidth - window.innerWidth,
  }));
  assert(viewportWidths.full > viewportWidths.visible, "original_image_not_scrollable_on_mobile");
  assert(viewportWidths.outerOverflow <= 1, "capture_preview_overflows_mobile_page");
  await imageViewport.focus();
  await page.keyboard.press("ArrowRight");
  await page.waitForFunction(() => document.querySelector(".capture-image-viewport").scrollLeft > 0);
  await page.screenshot({ path: path.join(output, "capture-mobile.png"), fullPage: true });
  await page.setViewportSize({ width: 1280, height: 900 });
  await rawTextField.fill("人工核对本次区域：保留原图与未校正的识别原文。");
  assert.equal(await immutableOcrText.innerText(),
    acceptedOcr.raw_text || "未识别到可用文字，请手动填写原始文本。");
  const previewConsent = page.getByRole("checkbox", {
    name: "我已核对原文、实例词条和完整构筑，确认这些输入。"
  });
  await previewConsent.check();
  const textBeforeRecapture = await rawTextField.inputValue();
  const ocrBeforeRecaptureFailure = ocrRequests;
  await page.evaluate(() => { window.__deskrawlMockState.scenario = "not_foreground"; });
  await windowCapture.click();
  await check("Deskrawl 不是当前前台窗口");
  await page.waitForFunction(() => {
    const button = [...document.querySelectorAll("button")]
      .find(item => item.textContent.includes("捕获所选游戏窗口区域并读取"));
    return button && !button.disabled;
  });
  assert.equal(await capturePreview.count(), 0, "failed_recapture_kept_previous_image");
  assert.equal(await page.getByText("已保留原始区域与识别原文；字段仍需逐项核对。", { exact: false }).count(), 0,
    "failed_recapture_kept_previous_observation");
  assert.equal(await previewConsent.isChecked(), false, "failed_recapture_kept_previous_confirmation");
  assert.equal(await rawTextField.inputValue(), textBeforeRecapture, "failed_recapture_erased_manual_text");
  assert.equal(ocrRequests, ocrBeforeRecaptureFailure, "failed_native_recapture_reached_ocr");
  await page.evaluate(() => { window.__deskrawlMockState.scenario = "success"; });
  await windowCapture.click();
  await capturePreview.waitFor({ state: "visible" });
  assert.equal(await previewConsent.isChecked(), false, "new_image_reused_old_confirmation");
  simulatedNativeChecks.push("original_region_review_preserves_raw_ocr_and_clears_stale_image_confirmation");

  await page.getByLabel("游戏范围", { exact: true }).fill("lootweave-fixture");
  assert.equal(await capturePreview.count(), 0, "scope_change_kept_previous_image");
  assert.equal(await page.getByText("已保留原始区域与识别原文；字段仍需逐项核对。", { exact: false }).count(), 0,
    "scope_change_kept_old_capture_association");
  await genericSource.selectOption("deskrawl");
  await page.evaluate(() => { window.__deskrawlMockState.scenario = "multiple"; });
  await page.getByRole("button", { name: "检测 / 重新检测 Deskrawl 窗口", exact: true }).click();
  await check("进程数：2");
  assert.equal(await windowSelector.inputValue(), "", "optional_deskrawl_source_auto_selected_window");
  await windowSelector.selectOption("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa");
  assert.equal(await windowCapture.isEnabled(), true, "optional_deskrawl_source_capture_not_enabled");
  await page.evaluate(() => { window.__deskrawlMockState.scenario = "success"; });
  const mismatchOcrRequest = page.waitForRequest("**/api/ocr/regions");
  await windowCapture.click();
  await page.getByRole("status").filter({ hasText: "3 秒后捕获" }).waitFor({ state: "visible" });
  await mismatchOcrRequest;
  await check("已保留原始区域与识别原文；字段仍需逐项核对。");
  await rawTextField.fill("人工填写的 Deskrawl 观察文本");
  await check("采集来源为 deskrawl，请先核对游戏范围，再确认快照。");
  const confirmationCheckbox = page.getByRole("checkbox", {
    name: "我已核对原文、实例词条和完整构筑，确认这些输入。"
  });
  assert.equal(await confirmationCheckbox.isDisabled(), true,
    "deskrawl_capture_could_be_confirmed_against_fixture_scope");
  assert.equal(await page.getByRole("button", { name: "确认并保存快照", exact: true }).isDisabled(), true,
    "snapshot_save_enabled_for_capture_scope_mismatch");
  simulatedNativeChecks.push("deskrawl_capture_context_cannot_confirm_against_fixture_scope");

  stage = "deskrawl_late_detection";
  await page.evaluate(() => { window.__deskrawlMockState.scenario = "delayed_not_running"; });
  await page.getByRole("button", { name: "检测 / 重新检测 Deskrawl 窗口", exact: true }).click();
  await page.getByRole("button", { name: "正在检测 Deskrawl…", exact: true }).waitFor();
  await page.getByLabel("游戏范围", { exact: true }).fill("deskrawl");
  await page.getByLabel("游戏范围", { exact: true }).fill("lootweave-fixture");
  await genericSource.selectOption("deskrawl");
  await page.evaluate(() => { window.__deskrawlMockState.scenario = "multiple"; });
  await page.getByRole("button", { name: "检测 / 重新检测 Deskrawl 窗口", exact: true }).click();
  await check("进程数：2");
  await windowSelector.waitFor({ state: "visible" });
  await page.evaluate(async () => {
    window.__deskrawlMockState.releaseDetection();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  });
  assert.equal(await page.evaluate(() => window.__deskrawlMockState.delayedDetectionFinished), true);
  assert.equal(await windowSelector.count(), 1, "late_detection_replaced_current_window_list");
  assert.equal(await backgroundOption.count(), 1, "late_detection_lost_current_window_binding");
  assert.equal(await windowSelector.inputValue(), "", "new_detection_silently_selected_window");
  simulatedNativeChecks.push("late_detection_from_previous_context_cannot_replace_new_window_list");
} catch (error) {
  process.exitCode = 1;
  let detail = String(error.message);
  if (credential) detail = detail.replaceAll(credential, "[redacted]");
  if (runtimeUrl) detail = detail.replaceAll(runtimeUrl, "[runtime-url]");
  failure = { name: error.name, detail: detail.slice(0, 2000) };
  console.error("UI check failed at " + stage + ": " + failure.detail);
  if (page) {
    failureScreenshot = "pending";
    await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true })
      .then(() => { failureScreenshot = "saved"; })
      .catch(error => { failureScreenshot = "failed_" + error.name; });
  }
} finally {
  if (browser) await browser.close().catch(() => {});
  let code = child.exitCode;
  if (code === null && child.signalCode === null) {
    const exited = wait("exit", child, 10000);
    child.stdin.end();
    try {
      [code] = await exited;
    } catch {
      if (child.exitCode === null && child.signalCode === null) child.kill();
      try { [code] = await wait("exit", child, 3000); }
      catch { code = child.exitCode; }
    }
  }
  if (code !== 0) process.exitCode = 1;
  const passed = !process.exitCode && code === 0;
  await writeFile(path.join(output, "report.json"), JSON.stringify({
    scope: "Fictional fixtures in a real browser with independently running Python services.",
    checks: results, simulated_native_checks: simulatedNativeChecks,
    flow_count: results.length + simulatedNativeChecks.length,
    stage, passed, browser_errors: errors, failure, failure_screenshot: failureScreenshot,
    runtime_exit_code: code, duration_seconds: (Date.now() - started) / 1000,
    limitations: [
      "Deskrawl process/window detection and capture IPC were simulated in-browser; no real native capture or game process was exercised.",
      "The mocked successful capture used a synthetic BMP; OCR, profile and other application HTTP services remained real local services.",
      "Historical 0.1.1 replay used a frozen fictional fixture seeded before startup, not customer data or current game acceptance.",
      "Clean-machine desktop distribution still needs separate evidence."
    ]
  }, null, 2) + "\n");
  if (code !== 0) console.error("Runtime cleanup failed.");
  else if (passed) console.log("UI checks passed: " + results.length + " real-service flows + " +
    simulatedNativeChecks.length + " simulated Deskrawl native flows.");
  console.log("Evidence: " + path.relative(root, output).replaceAll(path.sep, "/"));
}
