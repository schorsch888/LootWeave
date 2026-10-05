// Browser regression for LootWeave's own protocol, with fictional observations only.
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
const python = option("--python") || process.env.LOOTWEAVE_PYTHON || "python";
const output = path.join(root, ".local/live-import-check", randomUUID());
await mkdir(output, { recursive: true });
const fixtureCode = [
  "import json,sys",
  "sys.path.insert(0,'tests')",
  "from test_live_input import sample_document,equipment,run",
  "v=sample_document()",
  "v['items'][0]['name']='Fixture equipped wand'",
  "v['items'][1]['name']='Fixture backpack wand'",
  "v['items'][2]['name']='Fixture storage ring'",
  "v['items'].append(dict(equipment('blocked'),name='Fixture unsettled wand',settlement='pending'))",
  "v['items'].extend(dict(equipment('extra-'+str(i)),name='Fixture bag '+str(i+1).zfill(3)) for i in range(80))",
  "v['reports']['runs']['records'].extend(run('extra-run-'+str(i),v['reports']['runs']['records'][0]['t1']+50) for i in range(65))",
  "print(json.dumps(v))",
].join("\n");
const fixture = spawnSync(python, ["-c", fixtureCode], { cwd: root, encoding: "utf8", windowsHide: true, timeout: 10000 });
assert.ifError(fixture.error);
assert.equal(fixture.status, 0, "fictional_sample_creation_failed");
const sample = JSON.parse(fixture.stdout);
const checks = [];
const errors = [];
const paths = [];
let reads = 0;
let credential = "";
let runtimeUrl = "";
let browser;
let page;
let failure = null;
let stage = "startup";
const started = Date.now();

function start(args) {
  const child = spawn(python, args, { cwd: root, stdio: ["pipe", "pipe", "pipe"], windowsHide: true });
  child.stderrLog = "";
  child.done = new Promise(resolve => {
    child.once("error", () => resolve({ code: null, error: true }));
    child.once("exit", (code, signal) => resolve({ code, signal }));
  });
  child.stderr.on("data", chunk => { child.stderrLog = (child.stderrLog + chunk.toString("utf8")).slice(0, 65536); });
  child.ready = new Promise((resolve, reject) => {
    let buffer = "";
    const timer = setTimeout(() => reject(new Error("readiness_timeout")), 20000);
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
  return child;
}
async function stop(child) {
  child.stdin.end();
  let timer;
  const result = await Promise.race([child.done, new Promise(resolve => { timer = setTimeout(() => resolve(null), 10000); })]);
  clearTimeout(timer);
  if (result) { assert.equal(result.code, 0, "owned_runtime_cleanup_failed"); return; }
  child.kill();
  await child.done;
  throw new Error("owned_runtime_cleanup_timeout");
}
const runtime = start(["runtime.py", "--stdio-control", "--no-browser", "--startup-policy", "on-demand", "--data-dir", path.join(output, "state")]);
const sanitize = value => String(value).replaceAll(credential || "__no_credential__", "[session]").replaceAll(runtimeUrl || "__no_runtime_url__", "[local-runtime]");
const text = async value => { await page.getByText(value, { exact: false }).first().waitFor({ state: "visible" }); };
const nextRead = () => page.waitForResponse(response => new URL(response.url()).pathname === "/api/profile/imports/live/read");
async function api(route, data) {
  const response = await page.request.post(runtimeUrl + "/api/profile/" + route, { headers: { Authorization: "Bearer " + credential }, data });
  assert.equal(response.status(), 200, "local_api_" + route + "_failed");
  return response.json();
}
async function publish() {
  sample.captured_at = new Date().toISOString();
  const result = await api("live/samples", sample);
  assert.equal(result.state, "unconfirmed");
}
function counts() {
  const result = spawnSync(python, ["-c", "import json,sqlite3,sys; db=sqlite3.connect('file:'+sys.argv[1]+'?mode=ro',uri=True); print(json.dumps([db.execute('SELECT COUNT(*) FROM '+name).fetchone()[0] for name in ('observations','revisions')]))", path.join(output, "state/profile/profile.sqlite3")],
    { cwd: root, encoding: "utf8", windowsHide: true, timeout: 10000 });
  assert.equal(result.status, 0, "profile_counts_failed");
  return JSON.parse(result.stdout);
}

try {
  const ready = await runtime.ready;
  credential = ready.token;
  runtimeUrl = ready.url;
  const launch = { headless: true };
  if (process.platform === "win32") launch.channel = "msedge";
  if (option("--browser-executable")) { delete launch.channel; launch.executablePath = option("--browser-executable"); }
  browser = await chromium.launch(launch);
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", error => errors.push(error.name));
  page.on("request", request => {
    const pathname = new URL(request.url()).pathname;
    paths.push(pathname);
    if (pathname === "/api/profile/imports/live/read") reads++;
  });
  await page.goto(runtimeUrl + "/#session=" + credential);
  stage = "source_choice";
  await page.getByRole("radio", { name: "截图 OCR", exact: true }).check();
  await page.getByText("从截图识别装备字段", { exact: true }).waitFor({ state: "visible" });
  assert.equal(await page.locator("details").filter({ has: page.locator("summary", { hasText: "从截图识别装备字段" }) }).getAttribute("open"), "");
  await page.getByRole("radio", { name: "实时 API", exact: true }).check();
  const live = page.getByRole("region", { name: "实时 API 数据", exact: true });
  const scope = live.getByRole("checkbox", { name: "我已核对游戏构建 25690430、发行版本、模式和职业。", exact: true });
  const refresh = live.getByRole("button", { name: "读取／刷新当前数据", exact: true });
  const monitor = live.getByRole("checkbox", { name: "持续刷新（每次读取完成后等待 2 秒）", exact: true });
  const load = live.getByRole("button", { name: "载入候选与当前构筑", exact: true });
  const confirm = page.getByRole("checkbox", { name: "我已核对原文、实例词条和完整构筑，确认这些输入。", exact: true });
  await live.getByLabel("数据源标识", { exact: true }).and(page.locator(":enabled")).waitFor({ state: "visible" });
  assert.equal(await page.getByLabel("配对令牌", { exact: true }).count(), 0);
  assert.equal(reads, 0);
  await scope.check();
  let response = nextRead();
  await refresh.click();
  assert.equal((await response).status(), 404);
  await text("尚未收到这个数据源的观测");
  assert.deepEqual(counts(), [0, 0]);
  checks.push("source_choice_preserves_ocr_and_own_api_has_no_external_credentials_or_implicit_collection");

  stage = "own_input";
  await publish();
  const inputFile = path.join(output, "fictional-observation.json");
  await writeFile(inputFile, JSON.stringify(sample));
  const sent = spawnSync(python, ["scripts/send_live_sample.py", "--gateway", runtimeUrl, "--file", inputFile], {
    cwd: root, env: { ...process.env, LOOTWEAVE_LIVE_SESSION: credential }, encoding: "utf8", windowsHide: true, timeout: 10000,
  });
  assert.ifError(sent.error);
  assert.equal(sent.status, 0, "own_sender_failed");
  assert.equal(JSON.parse(sent.stdout).state, "unconfirmed");
  assert.equal(sent.stdout.includes(credential), false);
  await live.getByLabel("载入观测文件", { exact: true }).setInputFiles(inputFile);
  await scope.and(page.locator(":enabled")).waitFor({ state: "visible" });
  assert.equal(await scope.isChecked(), false);
  await scope.check();
  response = nextRead();
  await refresh.click();
  assert.equal((await response).status(), 200);
  await text("Synthetic hero");
  assert.deepEqual(counts(), [0, 0]);
  assert.equal(await live.getByRole("radio", { name: "选择 Fixture equipped wand", exact: true }).isDisabled(), true, "equipped_item_must_not_be_candidate");
  assert.equal(await live.getByRole("radio", { name: "选择 Fixture unsettled wand", exact: true }).isDisabled(), true, "pending_item_must_not_be_candidate");
  const inventory = live.getByRole("region", { name: "持有物品记录", exact: true });
  assert.equal(await inventory.locator("tbody tr").count(), 50);
  await live.getByRole("button", { name: "下一页", exact: true }).click();
  await inventory.getByRole("radio", { name: "选择 Fixture bag 080", exact: true }).waitFor({ state: "visible" });
  await live.getByRole("button", { name: "上一页", exact: true }).click();
  checks.push("own_http_sender_and_json_file_publish_unconfirmed_samples_and_inventory_pages_remain_bounded");

  stage = "independent_views";
  const beforeViews = reads;
  for (const name of ["角色状态", "战斗面板", "容量与材料", "跑图与统计", "掉落预览", "数据可用性", "实战伤害", "血脉记录", "配装资料", "采集状态"])
    await live.getByRole("button", { name, exact: true }).click();
  await live.getByRole("button", { name: "实战伤害", exact: true }).click();
  assert.equal(await live.locator("dl div").filter({ has: page.locator("dt", { hasText: "累计伤害计数" }) }).first().locator("dd").innerText(), "200");
  await live.getByRole("button", { name: "血脉记录", exact: true }).click();
  await live.getByLabel("记录来源", { exact: true }).selectOption("manual");
  await text("Fixture drawn wand");
  await live.getByRole("button", { name: "配装资料", exact: true }).click();
  await live.getByText("1 · Fixture boss build", { exact: true }).click();
  await text("位于仓库");
  assert.equal(await live.locator("details").filter({ has: page.locator("summary", { hasText: "Fixture boss build" }) }).count(), 1);
  await live.getByRole("button", { name: "跑图与统计", exact: true }).click();
  await live.getByRole("button", { name: "跑图记录下一页", exact: true }).click();
  await text("第 2／2 页");
  await live.getByRole("button", { name: "掉落预览", exact: true }).click();
  assert.equal(await live.getByRole("radio", { name: /选择 Fixture upcoming/ }).count(), 0);
  await live.getByRole("button", { name: "角色状态", exact: true }).click();
  assert.equal(reads, beforeViews);
  assert.equal(/retired-provider/i.test(await page.locator("body").innerText()), false);
  await page.screenshot({ path: path.join(output, "own-api-desktop.png"), fullPage: true });
  checks.push("ten_local_views_use_python_statistics_and_do_not_fetch_external_services_or_import_preview_items");

  stage = "continuous_refresh";
  response = nextRead();
  await monitor.check();
  const unchanged = await (await response).json();
  assert.equal(unchanged.unchanged, true);
  assert.equal("items" in unchanged, false);
  const beforeHidden = reads;
  await page.evaluate(() => {
    window.fixtureHidden = true;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => window.fixtureHidden });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(2300);
  assert.equal(reads, beforeHidden, "hidden_document_must_pause_refresh");
  await page.evaluate(() => {
    window.fixtureHidden = false;
    document.dispatchEvent(new Event("visibilitychange"));
  });
  sample.overview.character.hp.current = 179;
  sample.items[1].affixes[0].value = 44;
  await publish();
  response = nextRead();
  const changed = await (await response).json();
  assert.equal(changed.items.find(item => item.name === "Fixture backpack wand").affixes[0].value, 44);
  await live.getByRole("radio", { name: "选择 Fixture backpack wand", exact: true }).check();
  assert.equal(await monitor.isChecked(), false);
  assert.deepEqual(counts(), [0, 0]);
  checks.push("continuous_refresh_uses_thin_unchanged_replies_and_pauses_when_hidden_or_selected_without_sqlite_writes");

  stage = "frozen_draft_confirmation";
  sample.items[1].affixes[0].value = 99;
  await publish();
  await page.route("**/api/profile/imports/live/draft", async route => {
    const upstream = await route.fetch();
    const body = await upstream.json();
    body.response_hash = "b".repeat(64);
    await route.fulfill({ response: upstream, json: body });
  }, { times: 1 });
  await load.click();
  await text("数据来源已变化");
  assert.equal(await confirm.isDisabled(), true);
  let releaseDraft;
  const draftGate = new Promise(resolve => { releaseDraft = resolve; });
  await page.route("**/api/profile/imports/live/draft", async route => {
    await draftGate;
    await route.continue();
  }, { times: 1 });
  const pendingDraft = page.waitForRequest(request => new URL(request.url()).pathname === "/api/profile/imports/live/draft");
  try {
    await load.click();
    await pendingDraft;
    assert.equal(await confirm.isDisabled(), true, "pending_draft_must_not_enable_confirmation");
  } finally { releaseDraft(); }
  await confirm.and(page.locator(":enabled")).waitFor({ state: "visible" });
  await page.getByText("查看或编辑完整构筑数据", { exact: true }).click();
  const editor = page.getByLabel("完整构筑数据", { exact: true });
  let facts = JSON.parse(await editor.inputValue());
  assert.equal(facts.candidate_item.affixes[0].value, 44);
  assert.equal(facts.evidence[0].kind, "live_api_confirmation");
  assert.deepEqual(facts.observed_panel, []);
  assert.equal(JSON.stringify(facts).includes("Fixture upcoming wand"), false);
  assert.equal(JSON.stringify(facts).includes("Fixture sealed wand"), false);
  assert.equal(/retired-provider/i.test(JSON.stringify(facts)), false);
  assert.deepEqual(Object.fromEntries(facts.owned_resources.balances.map(row => [row.resource_id, row.amount])),
    { gold: 42, "live.FixtureIron": 5, "live.FixtureZero": 0 });
  response = nextRead();
  await refresh.click();
  await response;
  assert.equal(JSON.parse(await editor.inputValue()).candidate_item.affixes[0].value, 44);
  assert.equal(await confirm.isDisabled(), true);
  await live.getByRole("radio", { name: "选择 Fixture backpack wand", exact: true }).check();
  await load.click();
  await confirm.and(page.locator(":enabled")).waitFor({ state: "visible" });
  facts = JSON.parse(await editor.inputValue());
  assert.equal(facts.candidate_item.affixes[0].value, 99);
  await confirm.check();
  await page.getByRole("button", { name: "确认并保存快照", exact: true }).click();
  await text("输入已确认，可以比较完整配置");
  await text("快照 r1");
  const frozenEditor = await editor.inputValue();
  assert.equal(counts()[1], 1);
  checks.push("draft_identity_checks_and_explicit_confirmation_freeze_original_source_and_exclude_estimates_and_future_drops");

  stage = "scope_failure_and_mobile";
  sample.class_id = "hunter";
  await publish();
  response = nextRead();
  await monitor.check();
  assert.equal((await response).status(), 400);
  await text("持续刷新已停止");
  assert.equal(await monitor.isChecked(), false);
  assert.equal(await editor.inputValue(), frozenEditor);
  assert.equal(counts()[1], 1);
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  await page.screenshot({ path: path.join(output, "own-api-mobile.png"), fullPage: true });
  await page.getByRole("radio", { name: "截图 OCR", exact: true }).check();
  await page.getByRole("radio", { name: "实时 API", exact: true }).check();
  assert.equal(await live.getByRole("radio", { name: "选择 Fixture backpack wand", exact: true }).count(), 0);
  assert.equal(await confirm.isDisabled(), true);
  assert.equal(counts()[1], 1);
  assert.equal(paths.some(value => value.startsWith("/control/") || value.includes("/imports/retired-provider/")), false);
  assert.deepEqual(errors, []);
  checks.push("mismatched_scope_stops_monitor_and_source_switch_and_mobile_layout_preserve_saved_history");
} catch (error) {
  failure = { stage, message: sanitize(error instanceof Error ? error.message : error) };
  if (page) {
    try { await page.screenshot({ path: path.join(output, "failure.png"), fullPage: true }); }
    catch { /* Diagnostic screenshots are optional. */ }
  }
} finally {
  if (browser) await browser.close();
  try { await stop(runtime); }
  catch (error) { failure ||= { stage: "cleanup", message: sanitize(error.message) }; }
  if (failure && runtime.stderrLog) await writeFile(path.join(output, "runtime-error.private.txt"), sanitize(runtime.stderrLog));
  const report = { status: failure ? "failed" : "passed", checks, failure, elapsed_ms: Date.now() - started };
  await writeFile(path.join(output, "report.json"), JSON.stringify(report, null, 2));
  assert.equal(JSON.parse(await readFile(path.join(output, "report.json"), "utf8")).status, report.status);
}
if (failure) throw new Error(failure.stage + ": " + failure.message);
console.log(JSON.stringify({ status: "passed", checks: checks.length, output }));
