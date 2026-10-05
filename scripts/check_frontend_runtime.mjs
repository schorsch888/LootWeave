// Actual API/poller behavior with controlled HTTP/clock; direct activated-panel
// hooks/handlers. No DOM, browser/native input, performance or game acceptance.
import assert from "node:assert/strict";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "../frontend/node_modules/vite/dist/node/index.js";

const root = fileURLToPath(new URL("../", import.meta.url));
const panelSource = resolve(root, "frontend/src/shared/ui/activated-panel.tsx").replaceAll("\\", "/");
const server = await createServer({
  root: resolve(root, "frontend"), configFile: false, logLevel: "silent",
  server: { middlewareMode: true, hmr: false, watch: null },
  plugins: [{ name: "activated-panel-fixture", enforce: "pre", transform(code, id) {
    if (id.split("?")[0].replaceAll("\\", "/") !== panelSource) return;
    const hooks = 'import { useState } from "react";';
    assert.ok(code.includes(hooks));
    return code.replace(hooks, "const { useState } = globalThis.panelFixture;");
  } }],
});
globalThis.window = { location: { hash: "#session=synthetic-session", pathname: "/" } };
globalThis.sessionStorage = { getItem: () => "", setItem: () => {} };
globalThis.history = { replaceState: () => {} };
const flush = async () => { for (let i = 0; i < 4; i++) await new Promise(resolve => setImmediate(resolve)); };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const response = (body, ok = true) => ({ ok, status: ok ? 200 : 503, json: async () => body });
const ready = service => response({ service, state: "ready", generation: 1 });
const checks = [];
async function check(name, run) {
  try { await run(); checks.push({ name, passed: true }); }
  catch (error) { checks.push({ name, passed: false, error: error.message }); }
}
try {
  const { api, ensureService } = await server.ssrLoadModule("/src/shared/api/index.ts");
  const { pollRuntime } = await server.ssrLoadModule("/src/shared/runtime/index.ts");
  await check("concurrent OCR writes join one startup and preserve payloads/authentication", async () => {
    const start = deferred(), calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      if (url.endsWith("runtime/ensure")) return start.promise;
      return response({ accepted: true });
    };
    const bodies = [{ request_id: "ocr-first", image_base64: "synthetic-a" }, { request_id: "ocr-second", image_base64: "synthetic-b" }];
    const requests = bodies.map(body => api("ocr/regions", body));
    assert.equal(calls.length, 1);
    assert.deepEqual(JSON.parse(calls[0].options.body), { service: "ocr" });
    start.resolve(ready("ocr"));
    await Promise.all(requests);
    assert.deepEqual(calls.slice(1).map(call => JSON.parse(call.options.body)), bodies);
    assert(calls.every(call => call.options.headers.Authorization === "Bearer synthetic-session"));
  });
  await check("startup failure dispatches no write and only explicit retry starts again", async () => {
    const calls = [];
    let failed = true;
    globalThis.fetch = async (url, options) => {
      calls.push(url);
      return url.endsWith("runtime/ensure") ? failed ? response({ error: "service_unavailable" }, false) : ready(JSON.parse(options.body).service) : response({});
    };
    await assert.rejects(api("planning/trials", { trial_id: "stable-trial" }), /试验与样本服务未就绪.*请重试当前操作/);
    assert.deepEqual(calls, ["/api/runtime/ensure"]);
    failed = false;
    await api("planning/trials", { trial_id: "stable-trial" });
    assert.deepEqual(calls, ["/api/runtime/ensure", "/api/runtime/ensure", "/api/planning/trials"]);
  });
  await check("ambiguous dispatched write is not automatically replayed", async () => {
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push(url);
      if (url.endsWith("runtime/ensure")) return ready(JSON.parse(options.body).service);
      throw new TypeError("synthetic-lost-response");
    };
    await assert.rejects(api("profile/confirmations", { request_id: "stable-confirmation" }), /synthetic-lost-response/);
    assert.deepEqual(calls, ["/api/runtime/ensure", "/api/profile/confirmations"]);
  });
  await check("one cancelled startup waiter cannot cancel another caller or dispatch its write", async () => {
    const start = deferred(), controller = new AbortController(), calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      return url.endsWith("runtime/ensure") ? start.promise : response({});
    };
    const cancelled = api("ocr/regions", { request_id: "cancelled" }, { signal: controller.signal });
    const retained = api("ocr/regions", { request_id: "retained" });
    controller.abort();
    await assert.rejects(cancelled, { name: "AbortError" });
    assert.equal(calls[0].options.signal.aborted, false);
    start.resolve(ready("ocr"));
    await retained;
    assert.equal(calls.length, 2);
    assert.equal(JSON.parse(calls[1].options.body).request_id, "retained");
    await assert.rejects(api("planning/trials", {}, { signal: controller.signal }), { name: "AbortError" });
    assert.equal(calls.length, 2);
  });
  await check("every later business call rechecks owner readiness without cached stale routes", async () => {
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push(url);
      return url.endsWith("runtime/ensure") ? ready(JSON.parse(options.body).service) : response({});
    };
    await api("knowledge/packs"); await api("knowledge/packs");
    assert.deepEqual(calls, ["/api/runtime/ensure", "/api/knowledge/packs", "/api/runtime/ensure", "/api/knowledge/packs"]);
    calls.length = 0;
    await api("status"); await api("demo");
    assert.deepEqual(calls, ["/api/status", "/api/demo"]);
  });
  await check("wrong capability or invalid generation blocks business dispatch", async () => {
    for (const body of [{ service: "ocr", state: "ready", generation: -1 }, { service: "planning", state: "ready", generation: 1 }]) {
      let count = 0;
      globalThis.fetch = async () => { count++; return response(body); };
      await assert.rejects(api("ocr/regions", {}), /启动结果无法核验/);
      assert.equal(count, 1);
    }
  });
  await check("frozen collection, exact detail and replay preserve authentication without starting dependencies", async () => {
    const calls = [];
    const frozen = { evaluation_id: "frozen-v1", pin: { evaluator_version: "0.1.1" }, facts_hash: "frozen-input-hash" };
    globalThis.fetch = async (url, options) => {
      calls.push({ url, options });
      assert.notEqual(url, "/api/runtime/ensure", "history restarted live dependencies");
      return response(frozen);
    };
    assert.deepEqual(await api("evaluation/evaluations"), frozen);
    assert.deepEqual(await api("evaluation/evaluations/frozen-v1"), frozen);
    assert.deepEqual(await api("evaluation/evaluations/frozen-v1/replay", {}), frozen);
    assert.deepEqual(calls.map(call => [call.url, call.options.method]), [
      ["/api/evaluation/evaluations", "GET"], ["/api/evaluation/evaluations/frozen-v1", "GET"],
      ["/api/evaluation/evaluations/frozen-v1/replay", "POST"],
    ]);
    assert(calls.every(call => call.options.headers.Authorization === "Bearer synthetic-session"));
    assert(calls.every(call => call.options.signal instanceof AbortSignal));
    assert.equal(calls[2].options.body, "{}");
  });
  await check("new evaluation writes and malformed or wrong-method history paths still ensure", async () => {
    const calls = [];
    globalThis.fetch = async (url, options) => {
      calls.push({ url, body: options.body });
      return url.endsWith("runtime/ensure") ? ready(JSON.parse(options.body).service) : response({});
    };
    const requests = [["evaluation/evaluations", { request_id: "new-evaluation" }],
      ["evaluation/evaluations/frozen-v1", {}], ["evaluation/evaluations/frozen-v1/replay", undefined],
      ["evaluation/evaluations/", undefined], ["evaluation/evaluations/frozen-v1/extra", undefined],
      ["evaluation/evaluations/frozen-v1/replay/extra", {}], ["evaluation/evaluations//replay", {}],
      ["evaluation/evaluations/.", undefined], ["evaluation/evaluations/..", undefined],
      ["evaluation/evaluations/./replay", {}], ["evaluation/evaluations/../replay", {}],
      ["evaluation/evaluations/a%2Fb/replay", {}], ["evaluation/evaluations/" + "a".repeat(101), undefined]];
    for (const [path, body] of requests) await api(path, body);
    assert.equal(calls.length, requests.length * 2);
    for (let index = 0; index < requests.length; index++) {
      assert.equal(calls[index * 2].url, "/api/runtime/ensure");
      assert.equal(calls[index * 2].body, JSON.stringify({ service: "evaluation" }));
      assert.equal(calls[index * 2 + 1].url, "/api/" + requests[index][0]);
    }
    assert.equal(calls[1].body, JSON.stringify({ request_id: "new-evaluation" }));
  });
  await check("unavailable historical evaluator fails clearly without automatic startup or request retry", async () => {
    const calls = [];
    globalThis.fetch = async url => { calls.push(url); return response({ error: "service_start_required" }, false); };
    await assert.rejects(api("evaluation/evaluations"), /服务尚未启动.*重试所需服务/);
    assert.deepEqual(calls, ["/api/evaluation/evaluations"]);
    calls.length = 0;
    globalThis.fetch = async url => { calls.push(url); throw new TypeError("synthetic-replay-response-lost"); };
    await assert.rejects(api("evaluation/evaluations/frozen-v1/replay", {}), /synthetic-replay-response-lost/);
    assert.deepEqual(calls, ["/api/evaluation/evaluations/frozen-v1/replay"]);
  });
  await check("historical request cancellation aborts only its direct HTTP request", async () => {
    const controller = new AbortController(); let requests = 0, signal;
    globalThis.fetch = (url, options) => {
      assert.equal(url, "/api/evaluation/evaluations/frozen-v1");
      requests++; signal = options.signal;
      return new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("cancel", "AbortError")), { once: true }));
    };
    const pending = api("evaluation/evaluations/frozen-v1", undefined, { signal: controller.signal });
    controller.abort(); await assert.rejects(pending, { name: "AbortError" });
    assert.equal(signal.aborted, true); assert.equal(requests, 1);
    await assert.rejects(api("evaluation/evaluations", undefined, { signal: controller.signal }), { name: "AbortError" });
    assert.equal(requests, 1);
  });
  const state = []; let cursor = 0;
  globalThis.panelFixture = {
    useState(initial) { const index = cursor++; if (!(index in state)) state[index] = initial; return [state[index], next => { state[index] = typeof next === "function" ? next(state[index]) : next; }]; },
  };
  const { ActivatedPanel } = await server.ssrLoadModule("/src/shared/ui/activated-panel.tsx");
  // Finish Vite's asynchronous dependency work before intercepting global timers.
  // Its optimizer status timers must not enter the application's fake clock.
  await server.close();
  const realSetTimeout = globalThis.setTimeout, realClearTimeout = globalThis.clearTimeout;
  async function clockCheck(name, run) {
    await check(name, async () => {
      const timers = new Map(); let serial = 0;
      globalThis.setTimeout = (callback, delay) => { const id = ++serial; timers.set(id, { callback, delay }); return id; };
      globalThis.clearTimeout = id => timers.delete(id);
      try { await run(timers); }
      finally { globalThis.setTimeout = realSetTimeout; globalThis.clearTimeout = realClearTimeout; }
    });
  }
  await clockCheck("startup and business deadlines are separate and remain bounded", async timers => {
    const durations = [];
    globalThis.fetch = async (url, options) => {
      durations.push([...timers.values()].map(timer => timer.delay));
      return url.endsWith("runtime/ensure") ? ready(JSON.parse(options.body).service) : response({});
    };
    await api("ocr/regions", {});
    assert.deepEqual(durations, [[10000], [15000]]);
    assert.equal(timers.size, 0);
    globalThis.fetch = (_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("deadline", "AbortError")), { once: true }));
    const pending = ensureService("ocr");
    [...timers.values()][0].callback();
    await assert.rejects(pending, /请求超时.*请重试当前操作/);
    assert.equal(timers.size, 0);
  });
  await clockCheck("frozen-history requests retain the 15-second business deadline without a startup timer", async timers => {
    const deadlines = [];
    globalThis.fetch = async url => {
      assert.equal(url, "/api/evaluation/evaluations");
      deadlines.push([...timers.values()].map(timer => timer.delay));
      return response({ evaluations: [] });
    };
    await api("evaluation/evaluations");
    assert.deepEqual(deadlines, [[15000]]); assert.equal(timers.size, 0);
  });
  await clockCheck("slow status calls never overlap; visibility bursts queue one fresh return check", async timers => {
    const visibility = new EventTarget(); visibility.hidden = false;
    const pending = [], results = []; let failures = 0;
    globalThis.fetch = async url => { assert.equal(url, "/api/status"); const gate = deferred(); pending.push(gate); return gate.promise; };
    const poller = pollRuntime(value => results.push(value), () => failures++, visibility);
    try {
      assert.equal(pending.length, 1);
      for (let i = 0; i < 5; i++) { visibility.hidden = true; visibility.dispatchEvent(new Event("visibilitychange")); visibility.hidden = false; visibility.dispatchEvent(new Event("visibilitychange")); }
      assert.equal(pending.length, 1);
      pending[0].resolve(response({ core_ready: false, services: { knowledge: { state: "starting" } } })); await flush();
      assert.equal(pending.length, 2);
      pending[1].resolve(response({ core_ready: true, services: {} })); await flush();
      assert.equal(pending.length, 2);
      assert.equal([...timers.values()].filter(timer => timer.delay === 5000).length, 1);
      visibility.hidden = true; visibility.dispatchEvent(new Event("visibilitychange"));
      assert.deepEqual([...timers.values()].map(timer => timer.delay), [30000]);
      visibility.hidden = false; visibility.dispatchEvent(new Event("visibilitychange"));
      assert.equal(pending.length, 3);
      poller.stop();
      pending[2].resolve(response({ core_ready: false })); await flush();
      assert.equal(results.length, 2); assert.equal(failures, 0); assert.equal(timers.size, 0);
      visibility.dispatchEvent(new Event("visibilitychange")); assert.equal(pending.length, 3);
    } finally { poller.stop(); }
  });
  await clockCheck("stopping poller aborts active request and ignores its late failure", async timers => {
    let signal, count = 0, failures = 0;
    globalThis.fetch = (_url, options) => {
      count++; signal = options.signal;
      return new Promise((_resolve, reject) => signal.addEventListener("abort", () => reject(new DOMException("cancel", "AbortError")), { once: true }));
    };
    const visibility = new EventTarget(); visibility.hidden = false;
    const poller = pollRuntime(() => assert.fail("stopped callback"), () => failures++, visibility);
    poller.stop(); await flush();
    assert.equal(signal.aborted, true); assert.equal(failures, 0); assert.equal(timers.size, 0);
    visibility.dispatchEvent(new Event("visibilitychange")); assert.equal(count, 1);
  });
  await clockCheck("visible startup checks settle promptly; ready, permanently failed core and connection failures use idle interval", async timers => {
    const visibility = new EventTarget(); visibility.hidden = false;
    const statuses = [{ core_ready: false, services: { knowledge: { state: "starting" } } },
      { core_ready: true, services: {} },
      { core_ready: false, services: { profile: { state: "failed" }, knowledge: { state: "failed" }, evaluation: { state: "unavailable" } } }, "failed"]; let failures = 0;
    globalThis.fetch = async () => {
      const next = statuses.shift();
      if (next === "failed") throw new TypeError("synthetic-status-failure");
      return response(next);
    };
    const poller = pollRuntime(() => {}, () => failures++, visibility);
    try {
      await flush(); assert.deepEqual([...timers.values()].map(timer => timer.delay), [500]);
      poller.refresh(); await flush();
      assert.deepEqual([...timers.values()].map(timer => timer.delay), [5000]);
      poller.refresh(); await flush(); assert.equal(failures, 0);
      assert.deepEqual([...timers.values()].map(timer => timer.delay), [5000]);
      poller.refresh(); await flush(); assert.equal(failures, 1);
      assert.deepEqual([...timers.values()].map(timer => timer.delay), [5000]);
      visibility.hidden = true; visibility.dispatchEvent(new Event("visibilitychange"));
      assert.deepEqual([...timers.values()].map(timer => timer.delay), [30000]);
    } finally { poller.stop(); }
  });
  await check("secondary panel waits for activation and hiding retains its child identity", async () => {
    const child = { type: "synthetic-feature", key: "same-revision", props: { draft: "synthetic-draft" } };
    const render = () => { cursor = 0; return ActivatedPanel({ label: "测试面板", children: child }); };
    let tree = render(); assert.equal(tree.props.children[1], false);
    tree.props.children[0].props.onClick();
    tree = render(); assert.equal(tree.props.children[1].props.hidden, false);
    const original = tree.props.children[1].props.children;
    tree.props.children[0].props.onClick();
    tree = render(); assert.equal(tree.props.children[1].props.hidden, true);
    assert.equal(tree.props.children[1].props.children, original);
    tree.props.children[0].props.onClick();
    assert.equal(render().props.children[1].props.hidden, false);
  });
  console.log(JSON.stringify({ tests: checks.length, passed: checks.filter(check => check.passed).length, checks: checks.filter(check => !check.passed), scope: "Controlled HTTP/clock and direct component hooks; no DOM, browser, native input, performance or game acceptance." }));
  if (checks.some(check => !check.passed)) process.exitCode = 1;
} finally {
  await server.close();
  delete globalThis.panelFixture;
}
