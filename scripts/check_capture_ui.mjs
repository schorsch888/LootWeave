// Direct capture and confirmation handlers with fake hooks, native calls and timers.
// No browser, live IPC, screen capture, keyboard or mouse input is used.
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
import { createServer } from "../frontend/node_modules/vite/dist/node/index.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const capturePath = resolve(root, "frontend/src/features/capture-observation/index.tsx").replaceAll("\\", "/");
const confirmationPath = resolve(root, "frontend/src/features/confirm-snapshot/index.tsx").replaceAll("\\", "/");
const reportIndex = process.argv.indexOf("--report");
const reportPath = reportIndex >= 0 ? process.argv[reportIndex + 1] : undefined;
assert.ok(reportIndex < 0 || reportPath, "--report requires a new output path");
const checks = [], started = performance.now();
const server = await createServer({
  root: resolve(root, "frontend"), configFile: false, logLevel: "silent",
  server: { middlewareMode: true, hmr: false, watch: null },
  plugins: [{ name: "capture-fixture-adapter", enforce: "pre", transform(code, id) {
    const path = id.split("?")[0].replaceAll("\\", "/");
    if (path === capturePath) {
      const hooks = 'import { useEffect, useRef, useState } from "react";';
      const native = 'import { invoke, isTauri } from "@tauri-apps/api/core";';
      const api = 'import { api, newId, sessionCredential } from "../../shared/api";';
      assert.ok(code.includes(hooks) && code.includes(native) && code.includes(api), "Capture imports changed; update fixture adapter.");
      return code.replace(hooks, "const useEffect = (...args) => globalThis.captureFixture.useEffect(...args); const useRef = (...args) => globalThis.captureFixture.useRef(...args); const useState = (...args) => globalThis.captureFixture.useState(...args); const setTimeout = (...args) => globalThis.captureFixture.setTimeout(...args);")
        .replace(native, "const invoke = (...args) => globalThis.captureFixture.invoke(...args); const isTauri = () => true;")
        .replace(api, "const api = (...args) => globalThis.captureFixture.api(...args); const newId = (...args) => globalThis.captureFixture.newId(...args); const sessionCredential = () => 'fixture-only';");
    }
    if (path === confirmationPath) {
      const hooks = 'import { useState } from "react";';
      const api = 'import { api, newId } from "../../shared/api";';
      assert.ok(code.includes(hooks) && code.includes(api), "Confirmation imports changed; update fixture adapter.");
      return code.replace(hooks, "const useState = (...args) => globalThis.captureConfirmationFixture.useState(...args);")
        .replace(api, "const api = (...args) => globalThis.captureConfirmationFixture.api(...args); const newId = (...args) => globalThis.captureConfirmationFixture.newId(...args);");
    }
  } }],
});
function* nodes(value) {
  if (Array.isArray(value)) for (const child of value) yield* nodes(child);
  else if (value && typeof value === "object" && value.props) { yield value; yield* nodes(value.props.children); }
}
const find = (tree, predicate) => { const result = [...nodes(tree)].find(predicate); assert.ok(result, "Expected fixture control missing."); return result; };
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done; }); return { promise, resolve }; };
const gate = () => ({ entered: deferred(), released: deferred() });
const entered = async value => {
  let timeout;
  try { await Promise.race([value.entered.promise, new Promise((_, reject) => { timeout = setTimeout(() => reject(new Error("Persistence stage was not reached.")), 2000); })]); }
  finally { clearTimeout(timeout); }
};
const check = async (name, run) => { try { await run(); checks.push({ name, passed: true }); } catch (error) { checks.push({ name, passed: false, error: error.stack || error.message }); } };
const clock = 1767225600123;
const binding = "a".repeat(32);
const context = { game_id: "deskrawl", edition: "unknown", game_build: "unknown", mode: "online", season: "not_applicable", ruleset_id: "unknown", content_entitlements: [] };
const captureButton = tree => find(tree, node => node.type === "button" && typeof node.props.children === "string" &&
  (node.props.children === "捕获所选游戏窗口区域并读取" || node.props.children === "正在捕获与读取…" || /秒后捕获…$/.test(node.props.children)));

try {
  globalThis.window = { location: { hash: "", pathname: "/" } };
  globalThis.sessionStorage = { getItem: () => "", setItem() {} };
  globalThis.history = { replaceState() {} };
  const { CaptureObservationForm } = await server.ssrLoadModule("/src/features/capture-observation/index.tsx");
  const { ConfirmSnapshot } = await server.ssrLoadModule("/src/features/confirm-snapshot/index.tsx");
  const { emptySnapshot, mapReviewedItemFields } = await server.ssrLoadModule("/src/features/edit-equipment/model.ts");

  const makeCapture = (seed = {}) => {
    const states = [], deps = [], cleanups = [], effects = [];
    const calls = [], events = [], imported = [], errors = [], busy = [], delays = [], persisted = new Map();
    let cursor = 0, effectCursor = 0, serial = 0, nativeAttempts = 0, saveAttempts = 0, image;
    let props = { gameId: "deskrawl", contextKey: "fixture-context" };
    const fixture = {
      useState(initial) { const index = cursor++; if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
        return [states[index], next => { states[index] = typeof next === "function" ? next(states[index]) : next; }]; },
      useRef(initial) { const index = cursor++; if (!(index in states)) states[index] = { current: initial }; return states[index]; },
      useEffect(run, next) { const index = effectCursor++; if (!deps[index] || next.some((value, i) => !Object.is(value, deps[index][i]))) {
        deps[index] = next; effects.push(() => { cleanups[index]?.(); cleanups[index] = run(); }); } },
      setTimeout(callback, milliseconds) { delays.push(milliseconds); queueMicrotask(callback); return 0; },
      newId(prefix) { return prefix + "-" + (++serial); },
      async invoke(command, args) {
        calls.push({ kind: "native", command, args: structuredClone(args) });
        if (command === "detect_deskrawl_windows") return { game_id: "deskrawl", executable: "Deskrawl.exe", status: "running",
          process_count: 1, unavailable_processes: 0, version_verified: false, windows: [{ binding_id: binding, index: 1,
            status: "ready", client_bounds: { x: 100, y: 100, width: 1200, height: 700 }, can_select: true }] };
        assert.equal(command, "capture_deskrawl_region", "Unexpected native call; no live IPC is permitted.");
        assert.equal(args.bindingId, binding);
        nativeAttempts++;
        if (seed.failNativeAfter !== undefined && nativeAttempts > seed.failNativeAfter) throw new Error("capture_failed");
        image = { image_base64: Buffer.from("Synthetic image fixture " + nativeAttempts).toString("base64"),
          bounds: { x: 100 + args.x, y: 100 + args.y, width: args.width, height: args.height },
          capture_context: { format_version: 1, game_id: "deskrawl", executable: "Deskrawl.exe", window_binding: binding,
            client_bounds: { x: 100, y: 100, width: 1200, height: 700 }, relative_bounds: { x: args.x, y: args.y, width: args.width, height: args.height },
            verification: "foreground_before_and_after", captured_at_ms: clock + nativeAttempts * 1000, game_version: "unknown", game_build: "unknown" } };
        return structuredClone(image);
      },
      async api(path, body) {
        calls.push({ kind: "api", path, body: structuredClone(body) });
        if (path === "ocr/regions") {
          events.push("ocr:" + body.observation_id);
          if (seed.ocrGate) { seed.ocrGate.entered.resolve(); await seed.ocrGate.released.promise; }
          const imageHash = createHash("sha256").update(Buffer.from(body.image_base64, "base64")).digest("hex");
          return { observation_id: body.observation_id, method: "ocr", state: "unconfirmed", image_ref: "capture://" + imageHash,
            image_hash: imageHash, bounds: body.bounds, raw_text: nativeAttempts === 1 ? "Strength −18.25 points" : "Armor +7 points",
            language: body.language, fields: [], lines: [], requires_confirmation: true };
        }
        assert.equal(path, "profile/observations", "Unexpected API call; no real service or network is permitted.");
        events.push("save-start:" + body.observation_id); saveAttempts++;
        if (seed.profileGate) { seed.profileGate.entered.resolve(); await seed.profileGate.released.promise; }
        if (saveAttempts <= (seed.failSaves ?? 0)) throw new Error("fixture_profile_unavailable");
        const old = persisted.get(body.observation_id), result = { ...structuredClone(body), state: "unconfirmed" };
        if (old) assert.deepEqual(old, result, "Repeated observation metadata changed.");
        persisted.set(body.observation_id, result); events.push("save-done:" + body.observation_id);
        return structuredClone(result);
      },
    };
    const render = () => {
      globalThis.captureFixture = fixture; cursor = 0; effectCursor = 0;
      const tree = CaptureObservationForm({ ...props, onCaptured: observation => {
        assert.ok(persisted.has(observation.observation_id), "Imported capture has no persisted observation.");
        imported.push(structuredClone(observation)); events.push("import:" + observation.observation_id);
      }, onError: message => errors.push(message), onBusyChange: value => busy.push(value), onInvalidateCapture: () => events.push("invalidate") });
      for (const run of effects.splice(0)) run();
      return tree;
    };
    const prepare = async () => {
      const detect = find(render(), node => node.type === "button" && node.props.children === "检测 / 重新检测 Deskrawl 窗口");
      await detect.props.onClick();
      find(render(), node => node.type === "select" && [...nodes(node)].some(option => option.type === "option" && option.props.value === binding))
        .props.onChange({ target: { value: binding } });
      assert.equal(captureButton(render()).props.disabled, false);
    };
    return { render, prepare, capture: () => captureButton(render()).props.onClick(), calls, events, imported, errors, busy, delays, persisted,
      changeRegion() { const tree = render(); find(tree, node => node.type === "input" && node.props.value === 0).props.onChange({ target: { value: "1" } }); render(); },
      changeContext() { props = { ...props, contextKey: "changed-context" }; render(); },
      unmount() { for (const cleanup of cleanups) cleanup?.(); },
    };
  };

  const addCaptureFacts = (facts, observation, fields) => {
    const next = structuredClone(facts), id = "input-" + observation.observation_id;
    next.evidence.push({ id, kind: "ocr_confirmation", source_ref: "observation://" + observation.observation_id,
      captured_at: new Date(observation.capture_context.captured_at_ms).toISOString(), verification: "confirmed", conflicts: [] });
    next.candidate_item = mapReviewedItemFields(next.candidate_item, fields, id);
    return next;
  };
  const fresh = () => { const facts = emptySnapshot(context); facts.captured_at = new Date(clock).toISOString(); facts.evidence[0].captured_at = facts.captured_at; return facts; };
  const makeConfirmation = (facts, capture) => {
    const states = [], calls = []; let cursor = 0, serial = 0;
    const fixture = {
      useState(initial) { const index = cursor++; if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
        return [states[index], next => { states[index] = typeof next === "function" ? next(states[index]) : next; }]; },
      newId(prefix) { return prefix + "-confirm-" + (++serial); },
      async api(path, body) { calls.push({ path, body: structuredClone(body) });
        if (path === "profile/confirmations") return { revision: 1, facts: body.facts, build_hash: "fixture-hash", facts_hash: "fixture-facts-hash" };
        assert.equal(path, "profile/observations"); return structuredClone(body); },
    };
    const render = () => { globalThis.captureConfirmationFixture = fixture; cursor = 0; return ConfirmSnapshot({ facts, capture, captureReviewed: true,
      draftApplied: true, profileId: "capture-fixture-profile", revision: 0, rawText: "Player manually reconfirmed all listed values",
      onBusyChange() {}, onConfirmed() {}, onError: message => assert.fail(message) }); };
    return { calls, async submit() { find(render(), node => node.type === "input" && node.props.type === "checkbox").props.onChange({ target: { checked: true } });
      const save = find(render(), node => node.type === "button"); assert.equal(save.props.disabled, false); await save.props.onClick(); } };
  };
  const realProfile = (calls, sources) => {
    const python = String.raw`
import json, sys, tempfile
from pathlib import Path
from contracts import DomainError
from services.profile.app import Profile
payload = json.load(sys.stdin)
with tempfile.TemporaryDirectory(prefix="lootweave-capture-") as directory:
    target = Path(directory).resolve()
    assert target.is_relative_to(Path(tempfile.gettempdir()).resolve())
    app, saved, errors = Profile(target), None, []
    for call in payload["calls"]:
        try:
            result = app.handle("POST", "/v1/" + call["path"].removeprefix("profile/"), call["body"])
            if call["path"] == "profile/confirmations": saved = result
        except DomainError as error:
            errors.append({"path":call["path"],"code":error.code,"status":error.status})
    restarted = Profile(target)
    reopened = restarted.read(saved["profile_id"], saved["revision"]) if saved else None
    observations = {source:restarted.handle("GET", "/v1/observations/" + source, {}) for source in payload["sources"]}
    with restarted.connect() as db:
        counts = {table:db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in ("observations","revisions","confirmations")}
    print(json.dumps({"errors":errors,"reopened":reopened,"observations":observations,"counts":counts},ensure_ascii=True))
`;
    const result = spawnSync(process.env.LOOTWEAVE_PYTHON || "python", ["-B", "-c", python], {
      cwd: root, windowsHide: true, encoding: "utf8", input: JSON.stringify({ calls, sources }), timeout: 10000, maxBuffer: 2 * 1024 * 1024,
      env: { ...process.env, PYTHONUTF8: "1", PYTHONDONTWRITEBYTECODE: "1" },
    });
    assert.ifError(result.error); assert.equal(result.status, 0, result.stderr); const actual = JSON.parse(result.stdout);
    assert.deepEqual(actual.errors, []); assert.ok(actual.reopened); return actual;
  };
  const observationCalls = h => h.calls.filter(call => call.path === "profile/observations").map(({ path, body }) => ({ path, body }));
  const assertSource = (stored, source) => { assert.equal(stored.raw_text, source.raw_text); assert.equal(stored.image_hash, source.image_hash);
    assert.equal(stored.image_ref, source.image_ref); assert.deepEqual(stored.bounds, source.bounds); assert.deepEqual(stored.capture_context, source.capture_context); };

  await check("capture persists the unchanged source before importing facts and preview", async () => {
    const h = makeCapture(); await h.prepare(); await h.capture();
    assert.equal(h.imported.length, 1); const source = h.imported[0];
    assert.ok(h.events.indexOf("save-done:" + source.observation_id) < h.events.indexOf("import:" + source.observation_id));
    assertSource(h.persisted.get(source.observation_id), source);
    assert.equal(source.capture_context.captured_at_ms, clock + 1000); assert.equal(source.raw_text, "Strength −18.25 points");
    assert.deepEqual(h.delays, [1000, 1000, 1000]); assert.deepEqual(h.busy, [true, false]);
    assert.ok(find(h.render(), node => node.type === "img").props.src.startsWith("data:image/bmp;base64,"));
    h.unmount();
  });
  await check("observation persistence failure imports nothing and leaves retry available", async () => {
    const h = makeCapture({ failSaves: 1 }); await h.prepare(); await h.capture();
    assert.deepEqual(h.imported, []); assert.equal(h.persisted.size, 0); assert.equal(observationCalls(h).length, 1);
    assert.ok(![...nodes(h.render())].some(node => node.type === "img"));
    assert.ok(h.errors.includes("截图依据保存失败，请重试采集；文本输入仍可用。"));
    assert.equal(captureButton(h.render()).props.disabled, false); assert.deepEqual(h.busy, [true, false]);
    await h.capture(); assert.equal(h.imported.length, 1); assert.equal(h.persisted.size, 1); h.unmount();
  });
  await check("pending persistence stays busy and a changed region discards the import", async () => {
    const wait = gate(), h = makeCapture({ profileGate: wait }); await h.prepare(); const pending = h.capture();
    try { await entered(wait); assert.deepEqual(h.busy, [true]); assert.deepEqual(h.imported, []);
      assert.equal(captureButton(h.render()).props.disabled, true); h.changeRegion(); }
    finally { wait.released.resolve(); await pending; }
    assert.deepEqual(h.imported, []); assert.equal(h.persisted.size, 1); assert.deepEqual(h.busy, [true, false]);
    assert.ok(![...nodes(h.render())].some(node => node.type === "img"));
    assert.ok(h.errors.some(message => message.includes("已丢弃这次结果"))); h.unmount();
  });
  await check("context changes during OCR discard the result before persistence", async () => {
    const wait = gate(), h = makeCapture({ ocrGate: wait }); await h.prepare(); const pending = h.capture();
    try { await entered(wait); h.changeContext(); }
    finally { wait.released.resolve(); await pending; }
    assert.deepEqual(h.imported, []); assert.deepEqual(observationCalls(h), []); assert.equal(h.persisted.size, 0); h.unmount();
  });
  await check("unmounting during persistence cannot import a stale capture", async () => {
    const wait = gate(), h = makeCapture({ profileGate: wait }); await h.prepare(); const pending = h.capture();
    try { await entered(wait); h.unmount(); }
    finally { wait.released.resolve(); await pending; }
    assert.deepEqual(h.imported, []); assert.equal(h.persisted.size, 1);
  });
  await check("two captures preserve both sources before the later capture is confirmed in SQLite", async () => {
    const h = makeCapture(); await h.prepare(); await h.capture(); await h.capture();
    assert.equal(h.imported.length, 2); assert.equal(h.persisted.size, 2); const [one, two] = h.imported;
    assert.notEqual(one.observation_id, two.observation_id); assert.notEqual(one.image_hash, two.image_hash);
    let facts = addCaptureFacts(fresh(), one, [{ kind: "affix", id: "strength", value: -18.25, unit: "points" }]);
    facts = addCaptureFacts(facts, two, [{ kind: "affix", id: "armor", value: 7, unit: "points" }]);
    const confirm = makeConfirmation(facts, two); await confirm.submit();
    const actual = realProfile([...observationCalls(h), ...confirm.calls], [one.observation_id, two.observation_id]);
    assert.deepEqual(actual.counts, { observations: 2, revisions: 1, confirmations: 1 });
    assert.equal(actual.reopened.observation_time_status, "verified");
    for (const source of [one, two]) assertSource(actual.observations[source.observation_id], source);
    for (const [id, source] of [["strength", one], ["armor", two]]) {
      const roll = actual.reopened.facts.candidate_item.affixes.find(row => row.id === id);
      assert.deepEqual(roll.evidence_ids, ["input-" + source.observation_id]);
    }
    assert.equal(actual.reopened.facts.captured_at, facts.captured_at); h.unmount();
  });
  await check("failed recapture followed by manual confirmation keeps the original OCR source readable after restart", async () => {
    const h = makeCapture({ failNativeAfter: 1 }); await h.prepare(); await h.capture(); const source = h.imported[0];
    const facts = addCaptureFacts(fresh(), source, [{ kind: "affix", id: "strength", value: -18.25, unit: "points" }]);
    await h.capture(); assert.equal(h.imported.length, 1); assert.ok(![...nodes(h.render())].some(node => node.type === "img"));
    const confirm = makeConfirmation(facts); await confirm.submit();
    assert.equal(confirm.calls.find(call => call.path === "profile/observations").body.method, "text");
    const actual = realProfile([...observationCalls(h), ...confirm.calls], [source.observation_id]);
    assert.deepEqual(actual.counts, { observations: 2, revisions: 1, confirmations: 1 });
    assert.equal(actual.reopened.observation_time_status, "not_recorded"); assertSource(actual.observations[source.observation_id], source);
    const roll = actual.reopened.facts.candidate_item.affixes.find(row => row.id === "strength");
    assert.equal(roll.value, -18.25); assert.ok(roll.evidence_ids.includes("input-" + source.observation_id));
    const original = actual.reopened.facts.evidence.find(row => row.id === "input-" + source.observation_id);
    assert.equal(original.source_ref, "observation://" + source.observation_id); assert.equal(original.kind, "ocr_confirmation");
    assert.equal(original.captured_at, new Date(source.capture_context.captured_at_ms).toISOString()); h.unmount();
  });
} catch (error) { checks.push({ name: "fixture initialization", passed: false, error: error.stack || error.message }); }
finally { await server.close(); }
const passed = checks.every(check => check.passed) && checks.length > 0;
const report = { passed, duration_seconds: (performance.now() - started) / 1000,
  scope: "Direct React handlers with fake native calls/timers and real temporary Profile SQLite. No browser, screen capture or desktop input; not native OCR or real-game acceptance.", checks };
if (reportPath) writeFileSync(resolve(reportPath), JSON.stringify(report, null, 2) + "\n", { flag: "wx" });
for (const check of checks.filter(check => !check.passed)) console.error(check.name + ": " + check.error);
console.log("Capture persistence fixture checks: " + checks.filter(check => check.passed).length + "/" + checks.length + " passed; no browser or desktop input.");
process.exitCode = passed ? 0 : 1;
