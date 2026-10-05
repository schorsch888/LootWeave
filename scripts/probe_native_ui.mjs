// Probe only the WebView created by the native test harness. No screen pixels are read.
import { createRequire } from "node:module";
import http from "node:http";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { waitForNativePage } from "./native_page.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { chromium } = createRequire(path.join(root, "frontend/package.json"))("playwright");
const option = name => process.argv[process.argv.indexOf(name) + 1];
const port = Number(option("--port"));
const output = option("--output");
if (process.argv.includes("--interactive") || process.argv.includes("--full-flow")) throw new Error("interactive_probe_disabled");
if (!Number.isInteger(port) || port < 1 || port > 65535 || !output) throw new Error("probe_arguments_required");
if (!process.argv.includes("--passive")) throw new Error("probe_mode_required");
const expect = (condition, code) => { if (!condition) throw new Error(code); };
let browser;
let page;
let stage = "webview_connection";
let credential = "";
let connectionError = "unknown_error";
const connectionErrorCode = error => {
  const message = String(error?.message || "");
  if (message.includes("ECONNREFUSED")) return "connection_refused";
  if (message.includes("ECONNRESET")) return "connection_reset";
  if (error?.name === "TimeoutError" || message.includes("ETIMEDOUT")) return "connection_timeout";
  if (message.includes("Unexpected status")) return "http_unexpected_status";
  if (message.includes("Protocol error")) return "protocol_error";
  if (message.includes("WebSocket error") || message.includes("Unexpected server response")) return "websocket_rejected";
  return "unknown_error";
};
// Read only the owned loopback endpoint; never retain response URLs, paths or credentials.
const endpointStatus = () => new Promise(resolve => {
  const finish = value => { request.destroy(); resolve(value); };
  const request = http.get({ hostname: "127.0.0.1", port, path: "/json/version/", agent: false }, response => {
    response.on("error", () => {}); // A peer reset must not crash failure diagnostics.
    const status = response.statusCode;
    response.destroy();
    finish({ state: "responded", http_status: Number.isInteger(status) ? status : null });
  });
  request.setTimeout(500, () => finish({ state: "timeout" }));
  request.on("error", error => resolve({ state: error.code === "ECONNREFUSED" ? "connection_refused" : "connection_error" }));
});
const checks = [];
const errors = [];
const mode = "hidden_passive";
const report = { scope: mode + ": native WebView with frozen services and fictional facts.", mode, passed: false };
try {
  const deadline = Date.now() + 45000;
  while (!browser && Date.now() < deadline) {
    try { browser = await chromium.connectOverCDP("http://127.0.0.1:" + port, { timeout: 1500 }); }
    catch (error) { connectionError = connectionErrorCode(error); await new Promise(resolve => setTimeout(resolve, 200)); }
  }
  if (!browser) {
    report.connection_error_code = connectionError;
    report.loopback_endpoint = await endpointStatus();
  }
  expect(browser, "webview_connection_timeout");
  page = await waitForNativePage(browser, deadline);
  expect(page, "native_page_missing");
  page.setDefaultTimeout(15000);
  page.on("pageerror", error => errors.push(error.name));
  stage = "native_readiness";
  await page.getByRole("heading", { name: "每次换装，都有依据。" }).waitFor({ state: "visible" });
  await page.getByLabel("游戏范围", { exact: true }).waitFor({ state: "visible" });
  const url = new URL(page.url());
  expect(url.hostname === "127.0.0.1" && url.protocol === "http:" && !url.hash && !url.search, "native_session_not_removed");
  console.log(JSON.stringify({ event: "ready", webview_version: browser.version() }));
  checks.push("native_webview_loads_frozen_frontend");
  credential = await page.evaluate(() => sessionStorage.getItem("lootweave-session") || "");
  expect(credential.length === 64, "native_session_missing");
  stage = "native_ipc";
  const ipc = await page.evaluate(async () => {
    const invoke = window.__TAURI_INTERNALS__?.invoke?.bind(window.__TAURI_INTERNALS__);
    if (typeof invoke !== "function") return ["tauri_bindings_missing"];
    const token = sessionStorage.getItem("lootweave-session");
    const rejected = async sessionToken => {
      try { await invoke("capture_region", { sessionToken, x: 0, y: 0, width: 0, height: 0 }); return "unexpected_capture"; }
      catch (error) { return String(error); }
    };
    return [await rejected("0".repeat(64)), await rejected(token)];
  });
  report.native_rejections = ipc.map(value => String(value).replaceAll(credential, "[redacted]").slice(0, 384));
  expect(ipc[0] === "unauthorized", "native_capture_authorization_failed");
  expect(ipc[1] === "region_size_exceeded", "native_capture_bounds_failed");
  checks.push("native_capture_requires_session_and_valid_bounds");
  stage = "native_game_window_binding";
  const windowCheck = await page.evaluate(async () => {
    const invoke = window.__TAURI_INTERNALS__.invoke.bind(window.__TAURI_INTERNALS__);
    const sessionToken = sessionStorage.getItem("lootweave-session");
    const rejected = async (command, body) => {
      try { await invoke(command, body); return "unexpected_success"; }
      catch (error) { return String(error); }
    };
    const unauthorized = await rejected("detect_deskrawl_windows", { sessionToken: "0".repeat(64) });
    const expired = await rejected("capture_deskrawl_region", {
      sessionToken, bindingId: "invented", x: 0, y: 0, width: 0, height: 0,
    });
    const detection = await invoke("detect_deskrawl_windows", { sessionToken });
    const allowed = ["binding_id", "index", "status", "client_bounds", "can_select"];
    const privateMetadataExcluded = Array.isArray(detection.windows)
      && detection.windows.every(window => Object.keys(window).every(key => allowed.includes(key))
        && typeof window.binding_id === "string" && /^[0-9a-f]{32}$/.test(window.binding_id)
        && typeof window.can_select === "boolean");
    // Reject invalid dimensions even when a real game window happens to be present.
    // Never read pixels from the user's game or any other application.
    let invalidRegion = "game_window_binding_expired";
    if (detection.windows.length) {
      invalidRegion = await rejected("capture_deskrawl_region", {
        sessionToken, bindingId: detection.windows[0].binding_id,
        x: 0, y: 0, width: 0, height: 0,
      });
    }
    return { unauthorized, expired, invalidRegion, privateMetadataExcluded,
      game: detection.game_id, executable: detection.executable,
      versionVerified: detection.version_verified, status: detection.status,
      processCount: detection.process_count };
  });
  expect(windowCheck.unauthorized === "unauthorized", "native_window_detection_authorization_failed");
  expect(windowCheck.expired === "game_window_binding_expired", "native_window_binding_guard_failed");
  expect(windowCheck.privateMetadataExcluded && windowCheck.game === "deskrawl"
    && windowCheck.executable === "Deskrawl.exe" && windowCheck.versionVerified === false,
    "native_window_detection_contract_failed");
  expect(["not_running", "running", "no_window", "window_unavailable"].includes(windowCheck.status)
    && Number.isInteger(windowCheck.processCount) && windowCheck.processCount >= 0,
    "native_window_detection_status_failed");
  expect(["game_window_binding_expired", "game_window_minimized", "game_window_hidden",
    "game_window_unavailable", "game_window_not_foreground", "game_window_changed",
    "game_process_changed", "game_process_unavailable", "game_window_closed", "region_size_exceeded"]
    .includes(windowCheck.invalidRegion), "native_window_capture_bounds_failed");
  checks.push("native_deskrawl_metadata_binding_and_capture_guards");

  expect(errors.length === 0, "native_browser_error");
  report.passed = true;
} catch (error) {
  report.failure_code = /^[a-z_]+$/.test(error.message) ? error.message : error.name;
  process.exitCode = 1;
} finally {
  // Closing a connectOverCDP client releases its transport; native shutdown stays with the harness.
  if (browser) {
    try { await browser.close(); report.cdp_disconnected = true; }
    catch { report.cdp_disconnected = false; report.passed = false; report.failure_code = "cdp_disconnect_failed"; process.exitCode = 1; }
  }
  report.stage = stage;
  report.checks = checks;
  report.browser_errors = errors;
  await mkdir(output, { recursive: true });
  await writeFile(path.join(output, "probe.json"), JSON.stringify(report, null, 2) + "\n");
  console.log(JSON.stringify({ event: "complete", ...report }));
  // The harness closes its own native window after this client releases CDP.
  process.exit(process.exitCode || 0);
}
