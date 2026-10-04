import { useState } from "react";
import { api, isExactCount } from "../../shared/api";
import type { GameContext, Pack, Snapshot } from "../../shared/api";

type Props = {
  facts: Snapshot;
  revision: number;
  pack: Pack | null;
  onError: (message: string) => void;
};

type AcquisitionSource = {
  source_id: string;
  target_event: string;
  label?: string;
  eligibility: "active" | "inactive" | "unknown";
  min_level: number;
  conditions: string[];
  entitlements: string[];
  evidence_ids: string[];
};

type EligibilityResult = {
  scope_accepted: boolean;
  sources: AcquisitionSource[];
  notice: string;
  unknowns: string[];
};

type DropEstimate = {
  context: GameContext;
  target_event: string;
  attempt_unit: string;
  estimate: number;
  interval: [number, number];
  confidence_level: number;
  sample_size: number;
  observed_successes: number;
  method: string;
  assumptions: string[];
  notice: string;
};

const eligibilityLabel: Record<AcquisitionSource["eligibility"], string> = {
  active: "符合已知条件",
  inactive: "不符合已知条件",
  unknown: "条件未知",
};

const percent = (value: number) => {
  const scaled = value * 100;
  if (value > 0 && scaled < .05) return scaled.toExponential(1) + "%";
  if (value < 1 && scaled >= 99.95) return "<100%";
  return scaled.toFixed(1) + "%";
};

export function AcquisitionEvidence({ facts, revision, pack, onError }: Props) {
  const [eligibilityBusy, setEligibilityBusy] = useState(false);
  const [sampleBusy, setSampleBusy] = useState(false);
  const [eligibility, setEligibility] = useState<EligibilityResult>();
  const [estimate, setEstimate] = useState<DropEstimate>();
  const [targetEvent, setTargetEvent] = useState("");
  const [attemptUnit, setAttemptUnit] = useState("");
  const [attempts, setAttempts] = useState("100");
  const [successes, setSuccesses] = useState("0");
  const [allRecorded, setAllRecorded] = useState(false);
  const [versionUnchanged, setVersionUnchanged] = useState(false);

  const attemptCount = Number(attempts);
  const successCount = Number(successes);
  const countsValid = Boolean(isExactCount(attempts) && isExactCount(successes)
    && attemptCount > 0 && successCount >= 0 && successCount <= attemptCount);
  const sampleReady = revision > 0 && Boolean(targetEvent.trim()) && Boolean(attemptUnit.trim()) &&
    countsValid && allRecorded && versionUnchanged;
  const invalidateSample = () => { setEstimate(undefined); setAllRecorded(false); setVersionUnchanged(false); };

  const loadEligibility = async () => {
    if (!pack || revision <= 0) return;
    setEligibilityBusy(true);
    try {
      setEligibility(await api<EligibilityResult>("planning/sources/eligibility", {
        facts,
        pack_id: pack.pack_id,
        pack_version: pack.version,
        pack_hash: pack.pack_hash,
      }));
    } catch (error) {
      onError(error instanceof Error ? error.message : "获取来源条件失败。");
    } finally {
      setEligibilityBusy(false);
    }
  };

  const submitSample = async () => {
    if (sampleBusy || !sampleReady) return;
    setSampleBusy(true);
    setEstimate(undefined);
    onError("");
    try {
      setEstimate(await api<DropEstimate>("planning/drop-estimates", {
        context: facts.context,
        target_event: targetEvent.trim(),
        attempt_unit: attemptUnit.trim(),
        attempts: attemptCount,
        successes: successCount,
        coverage: allRecorded && versionUnchanged ? "complete" : "partial",
        version_unchanged: versionUnchanged,
        method: "observed_counts",
      }));
    } catch (error) {
      onError(error instanceof Error ? error.message : "观察样本未被接受。");
    } finally {
      setSampleBusy(false);
    }
  };

  return <section className="panel">
    <div className="section-heading">
      <div><span className="eyebrow">ACQUISITION EVIDENCE</span><h2>获取条件与手动观察</h2></div>
      <span className="tag">版本范围内</span>
    </div>
    <p className="muted">知识包是完全合成示例。此处只展示明确版本的资格条件，不推断掉落概率或获取难度；未知来源保持未知。</p>

    <div className="section-heading">
      <h3>来源资格条件</h3>
      <button type="button" onClick={loadEligibility} disabled={eligibilityBusy || revision <= 0 || !pack}>
        {eligibilityBusy ? "核对中…" : "核对当前条件"}
      </button>
    </div>
    {revision <= 0 || !pack
      ? <p className="muted" aria-live="polite">请先确认完整快照并选择明确版本的知识包，再核对来源条件。</p>
      : null}
    {eligibility && <div aria-live="polite">
      <p>{eligibility.scope_accepted ? "当前快照与知识包范围已接受。" : "当前范围未被接受；来源资格保持未知。"}</p>
      {eligibility.unknowns.map((unknown, index) => <p className="muted" key={`${unknown}-${index}`}>{unknown}</p>)}
      {eligibility.sources.length === 0
        ? <p className="muted">此版本知识包没有记录来源。</p>
        : eligibility.sources.map(source => <article className="reason" key={source.source_id}>
          <div className="section-heading">
            <strong>{source.label || source.source_id}</strong>
            <span>{eligibilityLabel[source.eligibility]}</span>
          </div>
          <p>来源 ID：{source.source_id} · 目标事件：{source.target_event} · 最低等级：{source.min_level}</p>
          <p>条件：{source.conditions.length ? source.conditions.join("、") : "无已记录条件"}</p>
          <p>内容权益：{source.entitlements.length ? source.entitlements.join("、") : "无"}</p>
          <p>证据 ID：{source.evidence_ids.length ? source.evidence_ids.join("、") : "无"}</p>
        </article>)}
      <p className="muted">{eligibility.notice}</p>
    </div>}
    <p className="muted">本面板不会自动新增或改写条件、权益。若来源仍未知，可在完整构筑 JSON 中填写信息并重新确认快照。</p>

    <details>
      <summary>记录一次人工观察样本</summary>
      <p className="muted">默认数字只是输入初值，不代表真实记录。只提交完整记录的尝试与结果，并确认期间版本和设置未变。</p>
      <fieldset className="draft-controls" disabled={sampleBusy}>
        <div className="fields">
          <label>目标事件<input value={targetEvent} onChange={event => { setTargetEvent(event.target.value); invalidateSample(); }} /></label>
          <label>一次尝试的单位<input value={attemptUnit} onChange={event => { setAttemptUnit(event.target.value); invalidateSample(); }} /></label>
          <label>尝试次数<input type="number" min="1" step="1" value={attempts} onChange={event => { setAttempts(event.target.value); invalidateSample(); }} /></label>
          <label>观察到成功次数<input type="number" min="0" step="1" value={successes} onChange={event => { setSuccesses(event.target.value); invalidateSample(); }} /></label>
        </div>
        <label className="check"><input type="checkbox" checked={allRecorded} onChange={event => { setAllRecorded(event.target.checked); setEstimate(undefined); }} />每次尝试及其结果都已完整记录</label>
        <label className="check"><input type="checkbox" checked={versionUnchanged} onChange={event => { setVersionUnchanged(event.target.checked); setEstimate(undefined); }} />观察期间版本及设置保持不变</label>
        {!countsValid && <p className="warning" role="status">请完整填写精确整数次数，满足 0 ≤ 成功次数 ≤ 尝试次数，且尝试次数大于 0。</p>}
        <button type="button" onClick={submitSample} disabled={sampleBusy || !sampleReady}>
          {sampleBusy ? "提交观察中…" : "提交完整观察样本"}
        </button>
        {revision <= 0 && <p className="muted">请先确认当前快照，才能记录样本。</p>}
      </fieldset>
      {estimate && <div aria-live="polite">
        <h3>记录样本的估计结果</h3>
        <p>样本范围：{estimate.context.game_id} · {estimate.context.edition} · build {estimate.context.game_build} · {estimate.context.mode} · {estimate.context.season} · {estimate.context.ruleset_id}</p>
        <p>内容权益：{estimate.context.content_entitlements.join("、") || "无"}</p>
        <p>提交事件：{estimate.target_event} · 尝试单位：{estimate.attempt_unit}</p>
        <p>估计比例：{percent(estimate.estimate)}；区间：{percent(estimate.interval[0])}–{percent(estimate.interval[1])}（{percent(estimate.confidence_level)}）</p>
        <p>样本量：{estimate.sample_size}；观察到的成功次数：{estimate.observed_successes}</p>
        <p className="muted">样本较少时区间可能较宽。观察结果不等于已验证的最终游戏概率。</p>
        <p className="muted">{estimate.notice}</p>
        <details><summary>后端方法与假设（原文）</summary>
          <p>Method: {estimate.method}</p>
          <ul>{estimate.assumptions.map((assumption, index) => <li key={`${index}-${assumption}`}>{assumption}</li>)}</ul>
        </details>
      </div>}
    </details>
  </section>;
}
