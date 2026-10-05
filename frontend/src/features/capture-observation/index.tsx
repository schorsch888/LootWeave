import { useEffect, useRef, useState } from "react";
import { invoke, isTauri } from "@tauri-apps/api/core";
import { api, newId, sessionCredential } from "../../shared/api";

type Bounds = { x: number; y: number; width: number; height: number };
type WindowStatus = "ready" | "background" | "minimized" | "hidden" | "window_unavailable";
type DeskrawlWindow = {
  binding_id: string;
  index: number;
  status: WindowStatus;
  client_bounds: Bounds | null;
  can_select: boolean;
};
type DeskrawlWindows = {
  game_id: "deskrawl";
  executable: "Deskrawl.exe";
  status: "not_running" | "running" | "no_window" | "window_unavailable";
  process_count: number;
  unavailable_processes: number;
  version_verified: boolean;
  windows: DeskrawlWindow[];
};
type CaptureContext = {
  format_version: 1;
  game_id: "deskrawl";
  executable: "Deskrawl.exe";
  window_binding: string;
  client_bounds: Bounds;
  relative_bounds: Bounds;
  verification: "foreground_before_and_after";
  captured_at_ms: number;
  game_version: string;
  game_build: string;
};
type CapturedImage = { image_base64: string; bounds: Bounds; capture_context?: CaptureContext };
type CaptureSource = "screen" | "deskrawl";

export type CaptureObservation = {
  observation_id: string;
  method: string;
  image_ref: string;
  image_hash: string;
  bounds: Bounds;
  raw_text: string;
  language: string;
  fields: { field: string; value: number | null; unit: string | null; ambiguous: boolean; raw_text?: string }[];
  requires_confirmation: boolean;
  capture_context?: CaptureContext;
  error?: string;
};

const windowStatusText: Record<WindowStatus, string> = {
  ready: "可选择 · 当前前台",
  background: "可选择 · 当前在后台，捕获前需手动切换到游戏",
  minimized: "已最小化 · 不可选择",
  hidden: "窗口隐藏 · 不可选择",
  window_unavailable: "窗口范围不可用 · 不可选择",
};

const detectionStatusText: Record<DeskrawlWindows["status"], string> = {
  not_running: "未检测到 Deskrawl.exe 正在运行。",
  running: "已检测到 Deskrawl.exe 进程。",
  no_window: "检测到 Deskrawl.exe，但没有可用窗口。",
  window_unavailable: "检测到 Deskrawl.exe，但进程或窗口信息不可用。",
};

const nativeErrors: Record<string, string> = {
  game_window_binding_expired: "窗口绑定已过期，请重新检测并选择窗口。",
  game_window_closed: "游戏窗口已关闭，请重新检测。",
  game_process_changed: "游戏进程已变化，请重新检测窗口。",
  game_process_unavailable: "无法读取游戏进程状态，请检查权限后重试。",
  game_window_minimized: "游戏窗口已最小化，请手动还原后重试。",
  game_window_hidden: "游戏窗口当前不可见，请手动显示后重试。",
  game_window_not_foreground: "Deskrawl 不是当前前台窗口；请手动切换到游戏后重试。",
  game_window_changed: "游戏窗口范围已变化，请重新检测并选择窗口。",
  game_window_unavailable: "游戏窗口范围暂不可用，请重新检测。",
  region_outside_game_window: "选择区域超出游戏客户区，请调整相对坐标。",
  region_size_exceeded: "选择区域超过捕获尺寸限制。",
  region_outside_screen: "游戏区域当前无法从屏幕读取，请重试。",
  game_detection_unavailable: "Windows 无法检测 Deskrawl 窗口；文本输入和历史记录仍可使用。",
  capture_unavailable: "Windows 屏幕捕获暂不可用。",
  capture_failed: "屏幕捕获失败，请重试。",
  capture_time_unavailable: "无法记录捕获时间，请重试。",
  unauthorized: "桌面会话已失效，请重新打开应用。",
};

function errorMessage(error: unknown, fallback: string): string {
  const code = typeof error === "string" ? error : error instanceof Error ? error.message : "";
  return nativeErrors[code] || fallback;
}

function validRegion(region: Bounds, bounds?: Bounds | null): boolean {
  if (!Number.isInteger(region.x) || !Number.isInteger(region.y) ||
      !Number.isInteger(region.width) || !Number.isInteger(region.height) ||
      region.x < 0 || region.y < 0 || region.width <= 0 || region.width > 1600 ||
      region.height <= 0 || region.height > 1200) return false;
  return !bounds || (region.x + region.width <= bounds.width && region.y + region.height <= bounds.height);
}

export function CaptureObservationForm({ gameId, contextKey, onCaptured, onError, onBusyChange, onInvalidateCapture }: {
  gameId: string;
  contextKey: string;
  onBusyChange: (busy: boolean) => void;
  onCaptured: (observation: CaptureObservation) => void;
  onError: (message: string) => void;
  onInvalidateCapture: () => void;
}) {
  const deskrawlScope = gameId.toLowerCase() === "deskrawl";
  const [region, setRegion] = useState<Bounds>({ x: 0, y: 0, width: 800, height: 500 });
  const [language, setLanguage] = useState("zh-Hans-CN");
  const [source, setSource] = useState<CaptureSource>(deskrawlScope ? "deskrawl" : "screen");
  const [detection, setDetection] = useState<DeskrawlWindows>();
  const [detectionMessage, setDetectionMessage] = useState("");
  const [selectedBinding, setSelectedBinding] = useState("");
  const [detecting, setDetecting] = useState(false);
  const [busy, setBusy] = useState(false);
  const [countdown, setCountdown] = useState(0);
  const [preview, setPreview] = useState<{ src: string; observation: CaptureObservation }>();
  const mounted = useRef(true);
  const detectionGeneration = useRef(0);
  const previousContext = useRef(`${gameId}\n${contextKey}`);
  const currentContext = `${gameId}\n${contextKey}`;
  const currentContextRef = useRef(currentContext);
  currentContextRef.current = currentContext;
  const currentSource = JSON.stringify([currentContext, source, selectedBinding, region, language]);
  const currentSourceRef = useRef(currentSource);
  currentSourceRef.current = currentSource;
  const selectedWindow = detection?.windows.find(window => window.binding_id === selectedBinding);
  const windowMode = deskrawlScope || source === "deskrawl";
  const windowModeRef = useRef(windowMode);
  windowModeRef.current = windowMode;
  const deskrawlRegionValid = Boolean(selectedWindow?.can_select && selectedWindow.client_bounds &&
    validRegion(region, selectedWindow.client_bounds));

  const invalidateCapture = () => { setPreview(undefined); onInvalidateCapture(); };

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; detectionGeneration.current++; };
  }, []);

  useEffect(() => {
    if (previousContext.current === currentContext) return;
    previousContext.current = currentContext;
    detectionGeneration.current++;
    setDetecting(false);
    setDetection(undefined);
    setDetectionMessage("");
    setSelectedBinding("");
    setSource(gameId.toLowerCase() === "deskrawl" ? "deskrawl" : "screen");
    invalidateCapture();
  }, [gameId, contextKey]);

  const refreshWindows = async () => {
    if (busy || detecting) return;
    const generation = ++detectionGeneration.current;
    setDetection(undefined);
    setDetectionMessage("");
    setSelectedBinding("");
    invalidateCapture();
    if (!isTauri()) {
      setDetectionMessage("Deskrawl 窗口检测需要 Windows 桌面入口；文本输入和历史记录仍可使用。");
      return;
    }
    const detectedContext = currentContext;
    setDetecting(true);
    try {
      const result = await invoke<DeskrawlWindows>("detect_deskrawl_windows", {
        sessionToken: sessionCredential(),
      });
      if (!mounted.current || detectionGeneration.current !== generation ||
          currentContextRef.current !== detectedContext || !windowModeRef.current) return;
      setDetection(result);
      setDetectionMessage("");
    } catch (error) {
      if (mounted.current && detectionGeneration.current === generation &&
          currentContextRef.current === detectedContext && windowModeRef.current) {
        setDetectionMessage(errorMessage(error, "Deskrawl 窗口检测失败，请从 Windows 桌面入口重试。"));
      }
    } finally {
      if (mounted.current && detectionGeneration.current === generation) setDetecting(false);
    }
  };

  const selectSource = (next: CaptureSource) => {
    if (next === source) return;
    detectionGeneration.current++;
    setDetecting(false);
    setSource(next);
    setDetection(undefined);
    setDetectionMessage("");
    setSelectedBinding("");
    invalidateCapture();
  };

  const setWindowBinding = (bindingId: string) => {
    if (bindingId === selectedBinding) return;
    setSelectedBinding(bindingId);
    invalidateCapture();
  };

  const setRegionValue = (key: keyof Bounds, value: number) => {
    setRegion(current => ({ ...current, [key]: value }));
    invalidateCapture();
  };

  const capture = async () => {
    if (busy || (windowMode && !deskrawlRegionValid)) return;
    const sourceAtStart = currentSourceRef.current;
    const bindingId = selectedBinding;
    invalidateCapture();
    onError("");
    setBusy(true);
    onBusyChange(true);
    try {
      let image: CapturedImage;
      if (windowMode) {
        for (let remaining = 3; remaining > 0; remaining--) {
          setCountdown(remaining);
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
        setCountdown(0);
        if (!mounted.current) return;
        if (currentSourceRef.current !== sourceAtStart) {
          onError("捕获来源或范围已变化，请重新选择并捕获。");
          return;
        }
        image = await invoke<CapturedImage>("capture_deskrawl_region", {
          sessionToken: sessionCredential(), bindingId, ...region,
        });
      } else {
        image = await invoke<CapturedImage>("capture_region", {
          ...region, sessionToken: sessionCredential(),
        });
      }
      if (!mounted.current) return;
      if (currentSourceRef.current !== sourceAtStart) {
        onError("捕获来源或范围已变化，已丢弃这次结果；请重新选择并捕获。");
        return;
      }
      const observation = await api<CaptureObservation>("ocr/regions", {
        observation_id: newId("capture"), ...image, language,
      });
      if (!mounted.current) return;
      if (currentSourceRef.current !== sourceAtStart) {
        onError("捕获来源或范围已变化，已丢弃这次结果；请重新选择并捕获。");
        return;
      }
      setPreview({ src: "data:image/bmp;base64," + image.image_base64, observation });
      onCaptured({ ...observation, ...(image.capture_context ? { capture_context: image.capture_context } : {}) });
      if (observation.error) onError("此语言的识别暂不可用，请通过原始文本和完整构筑手动确认。");
    } catch (error) {
      if (!mounted.current) return;
      onError(errorMessage(error, windowMode
        ? "游戏窗口捕获未完成。请确认已选择可用窗口并手动切换到 Deskrawl。"
        : "区域捕获未完成。请使用 Windows 桌面入口，并检查屏幕坐标；文本输入仍可用。"));
    } finally {
      if (mounted.current) {
        setCountdown(0);
        setBusy(false);
        onBusyChange(false);
      }
    }
  };

  const statusText = detection ? [
    detectionStatusText[detection.status],
    `进程数：${detection.process_count}`,
    `不可读取的进程：${detection.unavailable_processes}`,
    detection.version_verified ? "游戏版本已验证。" : "游戏版本尚未验证。",
  ].join(" ") : "";

  return <details>
    <summary>{deskrawlScope ? "从 Deskrawl 游戏窗口读取（Windows 桌面）" : "从屏幕区域读取（Windows 桌面）"}</summary>
    <p className="muted">{deskrawlScope
      ? "Deskrawl 范围固定使用明确选择的游戏窗口。坐标为相对客户区原点的物理像素；不会启动或切换游戏。"
      : "填写要读取的屏幕区域。只捕获你选择的范围，所有识别结果都需要核对。"}</p>
    {!deskrawlScope && <label>捕获来源<select value={source} onChange={event => selectSource(event.target.value as CaptureSource)}>
      <option value="screen">所选屏幕区域</option>
      <option value="deskrawl">明确选择 Deskrawl 窗口</option>
    </select></label>}
    {windowMode && <div>
      <button type="button" onClick={refreshWindows} disabled={busy || detecting}>
        {detecting ? "正在检测 Deskrawl…" : "检测 / 重新检测 Deskrawl 窗口"}
      </button>
      <p className="muted" role="status" aria-live="polite">{detectionMessage || statusText || "尚未检测 Deskrawl 窗口。"}</p>
      {detection && detection.windows.length > 0 && <label>选择 Deskrawl 窗口（不会自动选择）
        <select value={selectedBinding} onChange={event => setWindowBinding(event.target.value)} disabled={busy || detecting}>
          <option value="">请选择窗口</option>
          {detection.windows.map(window => <option key={window.binding_id} value={window.binding_id} disabled={!window.can_select}>
            窗口 {window.index} · {windowStatusText[window.status]}
          </option>)}
        </select>
      </label>}
      {windowMode && !deskrawlScope && <p className="muted">此来源读取所选 Deskrawl 客户区内的屏幕区域。游戏范围、版本和构筑仍需单独核对。</p>}
    </div>}
    <div className="fields">
      {(["x", "y", "width", "height"] as const).map(key => <label key={key}>{windowMode
        ? ({ x: "客户区左侧坐标（物理像素）", y: "客户区顶部坐标（物理像素）", width: "区域宽度（物理像素）", height: "区域高度（物理像素）" })[key]
        : ({ x: "左侧坐标", y: "顶部坐标", width: "区域宽度", height: "区域高度" })[key]}
        <input type="number" min={windowMode ? key === "width" || key === "height" ? 1 : 0 : undefined} value={region[key]}
          onChange={event => setRegionValue(key, Number(event.target.value))}/>
      </label>)}
    </div>
    {windowMode && selectedWindow?.client_bounds && <p className="muted">
      客户区：{selectedWindow.client_bounds.width} × {selectedWindow.client_bounds.height} 物理像素。区域必须完整位于客户区内。
    </p>}
    <label>识别语言<select value={language} onChange={event => { setLanguage(event.target.value); invalidateCapture(); }}>
      <option value="zh-Hans-CN">简体中文</option><option value="en-US">English</option><option value="de-DE">Deutsch</option>
    </select></label>
    {countdown > 0 && <p className="notice" role="status" aria-live="assertive">
      {countdown} 秒后捕获。请手动切换到 Deskrawl，并确保所选区域未被遮挡。
    </p>}
    <button type="button" onClick={capture} disabled={busy || (windowMode && !deskrawlRegionValid)}>
      {busy ? countdown ? `${countdown} 秒后捕获…` : "正在捕获与读取…" : windowMode ? "捕获所选游戏窗口区域并读取" : "捕获所选区域并读取"}
    </button>

    {preview && <figure className="capture-review">
      <figcaption>本次捕获原图 · {preview.observation.bounds.width} × {preview.observation.bounds.height} 物理像素</figcaption>
      <p className="muted">核对画面是否被遮挡，以及文字、符号和单位是否正确。原图按原始像素显示，可滚动查看；修改下方原始文本与完整构筑后仍需明确确认。</p>
      <div className="capture-image-viewport" role="region" aria-label="原始区域查看区" tabIndex={0}>
        <img src={preview.src} alt="本次捕获的原始区域"
          width={preview.observation.bounds.width} height={preview.observation.bounds.height}/>
      </div>
      <p className="muted">OCR 识别原文（未校正）</p>
      <pre aria-label="OCR 识别原文（未校正）">{preview.observation.raw_text || "未识别到可用文字，请手动填写原始文本。"}</pre>
    </figure>}
  </details>;
}
