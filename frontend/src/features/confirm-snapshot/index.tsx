import { useState } from "react";
import { api, newId } from "../../shared/api";
import type { Snapshot } from "../../shared/api";

type Capture = { observation_id: string; method: string; image_ref: string; bounds: Record<string, number>; raw_text: string; capture_context?: { game_id: string; captured_at_ms?: number } };
type Props = { onBusyChange: (busy: boolean) => void; draftApplied: boolean; capture?: Capture; facts: Snapshot; rawText: string; profileId: string; revision: number; onConfirmed: (revision: number, confirmed: Snapshot, buildHash: string) => void; onError: (message: string) => void };

export function ConfirmSnapshot({ onBusyChange, draftApplied, capture, facts, rawText, profileId, revision, onConfirmed, onError }: Props) {
  const sourceGame = capture?.capture_context?.game_id;
  const sourceMatches = !sourceGame || sourceGame === facts.context.game_id;
  const captureMs = capture?.capture_context?.captured_at_ms;
  const capturedAt = typeof captureMs === "number" && Number.isSafeInteger(captureMs) && captureMs > 0
    && captureMs <= 253402300799999 ? new Date(captureMs).toISOString() : undefined;
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ key: string; observationId: string; requestId: string }>();
  const submit = async () => {
    if (!checked || busy || !draftApplied || !sourceMatches) return;
    setBusy(true);
    onBusyChange(true);
    const key = JSON.stringify({ capture, facts, rawText, profileId, revision });
    const request = pending?.key === key ? pending : { key, observationId: capture?.observation_id || newId("text"), requestId: newId("confirm") };
    setPending(request);
    try {
      await api("profile/observations", capture ? { ...capture, raw_text: capture.raw_text } : { observation_id: request.observationId, method: "text", raw_text: rawText });
      const confirmed = structuredClone(facts);
      for (const evidence of confirmed.evidence) {
        if (evidence.source_ref.startsWith("observation://")) { evidence.source_ref = "observation://" + request.observationId;  }
      }
      const result = await api<{ revision: number; facts: Snapshot; facts_hash: string; build_hash: string; observation_time_status?: string }>("profile/confirmations", {
        request_id: request.requestId, profile_id: profileId, observation_id: request.observationId,
        expected_revision: revision, player_confirmed: true, facts: confirmed,
      });
      if (result.observation_time_status && !["verified", "not_recorded"].includes(result.observation_time_status)) {
        throw new Error("保存的快照与原始采集时间存在冲突，请核对时间后保存新修订；历史记录保持不变。");
      }
      onConfirmed(result.revision, result.facts, result.build_hash);
      setPending(undefined);
      setChecked(false);
    } catch (error) {
      onError(error instanceof Error ? error.message : "确认失败。");
    } finally {
      setBusy(false);
      onBusyChange(false);
    }
  };
  return <div className="confirmation">
    {capturedAt && <p className="muted">原始截图采集时间（UTC）：<time dateTime={capturedAt}>{capturedAt}</time>。请将这份截图的关联依据记在该时点；其他时点的来源应保留原时间。</p>}
    {!sourceMatches && <p className="warning">采集来源为 {sourceGame}，请先核对游戏范围，再确认快照。</p>}
    {!draftApplied && <p className="warning">请先应用完整构筑修改，再确认快照。</p>}
    <label className="check"><input disabled={!draftApplied || !sourceMatches} type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/>我已核对原文、实例词条和完整构筑，确认这些输入。</label>
    <button className="primary" type="button" onClick={submit} disabled={!checked || busy || !rawText.trim() || !draftApplied || !sourceMatches}>{busy ? "正在保存…" : "确认并保存快照"}</button>
  </div>;
}
