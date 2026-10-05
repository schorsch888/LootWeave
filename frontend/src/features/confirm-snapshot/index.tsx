import { useState } from "react";
import { api, newId } from "../../shared/api";
import type { Snapshot } from "../../shared/api";

type Capture = { observation_id: string; method: string; image_ref: string; bounds: Record<string, number>; raw_text: string; capture_context?: { game_id: string; captured_at_ms?: number } };
type Props = { onBusyChange: (busy: boolean) => void; draftApplied: boolean; captureReviewed?: boolean; capture?: Capture; facts: Snapshot; rawText: string; profileId: string; revision: number; onConfirmed: (revision: number, confirmed: Snapshot, buildHash: string) => void; onError: (message: string) => void };

export function ConfirmSnapshot({ onBusyChange, draftApplied, captureReviewed = false, capture, facts, rawText, profileId, revision, onConfirmed, onError }: Props) {
  const sourceGame = capture?.capture_context?.game_id;
  const sourceMatches = !sourceGame || sourceGame === facts.context.game_id;
  const reviewComplete = !capture || captureReviewed;
  const captureMs = capture?.capture_context?.captured_at_ms;
  const capturedAt = typeof captureMs === "number" && Number.isSafeInteger(captureMs) && captureMs > 0
    && captureMs <= 253402300799999 ? new Date(captureMs).toISOString() : undefined;
  const [checked, setChecked] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ key: string; observationId: string; requestId: string; inputEvidenceId: string }>();
  const submit = async () => {
    if (!checked || busy || !draftApplied || !sourceMatches || !reviewComplete) return;
    setBusy(true);
    onBusyChange(true);
    const key = JSON.stringify({ capture, facts, rawText, profileId, revision });
    const request = pending?.key === key ? pending : { key, observationId: capture?.observation_id || newId("text"), requestId: newId("confirm"), inputEvidenceId: newId("input") };
    setPending(request);
    try {
      await api("profile/observations", capture ? { ...capture, raw_text: capture.raw_text } : { observation_id: request.observationId, method: "text", raw_text: rawText });
      const confirmed = structuredClone(facts);
      const sourceRef = "observation://" + request.observationId;
      const addRefs = (value: { evidence_ids: string[] }, ids: string[]) => {
        value.evidence_ids = [...new Set([...value.evidence_ids, ...ids])];
      };
      if (capture) {
        let linked = confirmed.evidence.filter(evidence => evidence.source_ref === sourceRef);
        if (!linked.length) {
          const evidence = { id: request.inputEvidenceId, kind: "ocr_confirmation", source_ref: sourceRef,
            captured_at: capturedAt || facts.captured_at, verification: "confirmed", conflicts: [] };
          confirmed.evidence.push(evidence);
          linked = [evidence];
        }
        addRefs(confirmed, linked.map(evidence => evidence.id));
      } else {
        confirmed.evidence.push({ id: request.inputEvidenceId, kind: "manual_confirmation", source_ref: sourceRef,
          captured_at: facts.captured_at, verification: "confirmed", conflicts: [] });
        const ids = [request.inputEvidenceId];
        addRefs(confirmed, ids);
        for (const item of [...Object.values(confirmed.equipped_items), confirmed.candidate_item, ...(confirmed.inventory_items ?? [])]) {
          addRefs(item, ids);
          for (const affix of item.affixes) addRefs(affix, ids);
          for (const embedded of item.embedded_items) addRefs(embedded, ids);
        }
        for (const sources of [confirmed.skills, confirmed.talents, confirmed.paragon, confirmed.runes,
          confirmed.companions, confirmed.temporary_effects, confirmed.observed_panel]) {
          for (const source of sources) addRefs(source, ids);
        }
        for (const balance of confirmed.owned_resources?.balances ?? []) addRefs(balance, ids);
        for (const option of confirmed.preparation_options ?? []) {
          addRefs(option, ids);
          addRefs(option.result, ids);
          if (option.kind === "equipment") {
            for (const affix of option.result.affixes) addRefs(affix, ids);
            for (const embedded of option.result.embedded_items) addRefs(embedded, ids);
          }
        }
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
    {!reviewComplete && <p className="warning">请先逐行采用或忽略截图内容，并应用核对结果。</p>}
    {!draftApplied && <p className="warning">请先应用完整构筑修改，再确认快照。</p>}
    <label className="check"><input disabled={!draftApplied || !sourceMatches || !reviewComplete} type="checkbox" checked={checked} onChange={e => setChecked(e.target.checked)}/>我已核对原文、实例词条和完整构筑，确认这些输入。</label>
    <button className="primary" type="button" onClick={submit} disabled={!checked || busy || !rawText.trim() || !draftApplied || !sourceMatches || !reviewComplete}>{busy ? "正在保存…" : "确认并保存快照"}</button>
  </div>;
}
