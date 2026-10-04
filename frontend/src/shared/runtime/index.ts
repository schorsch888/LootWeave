import { api } from "../api";
import type { RuntimeStatus } from "../api";

const STARTUP_POLL_MS = 500;
const READY_POLL_MS = 5000;
const HIDDEN_POLL_MS = 30000;

// Readiness gates refresh promptly during startup; established services retain
// the prior visible interval. Resource/latency effects still need measurement.
export function pollRuntime(onStatus: (status: RuntimeStatus) => void, onError: () => void, visibility: Document = document) {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let active: AbortController | undefined;
  let refreshPending = false;
  let awaitingCore = true;
  const interval = () => visibility.hidden ? HIDDEN_POLL_MS : awaitingCore ? STARTUP_POLL_MS : READY_POLL_MS;
  const refresh = () => {
    if (stopped) return;
    clearTimeout(timer);
    timer = undefined;
    if (active) { refreshPending = true; return; }
    const controller = new AbortController();
    active = controller;
    void api<RuntimeStatus>("status", undefined, { signal: controller.signal })
      .then(status => {
        if (stopped) return;
        awaitingCore = !status.core_ready && ["profile", "knowledge", "evaluation"].some(service =>
          status.services[service]?.state === "dormant" || status.services[service]?.state === "starting");
        onStatus(status);
      })
      .catch(() => { if (!stopped) { awaitingCore = false; onError(); } })
      .finally(() => {
        active = undefined;
        if (stopped) return;
        if (refreshPending) { refreshPending = false; refresh(); }
        else timer = setTimeout(refresh, interval());
      });
  };
  const onVisibility = () => {
    if (!visibility.hidden) refresh();
    else if (!active) {
      clearTimeout(timer);
      timer = setTimeout(refresh, HIDDEN_POLL_MS);
    }
  };
  visibility.addEventListener("visibilitychange", onVisibility);
  refresh();
  return {
    refresh,
    stop() {
      stopped = true;
      clearTimeout(timer);
      visibility.removeEventListener("visibilitychange", onVisibility);
      active?.abort();
    },
  };
}
