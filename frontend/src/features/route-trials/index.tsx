import { useState } from "react";
import { api, isExactCount, newId } from "../../shared/api";
import type { Snapshot } from "../../shared/api";

type Route = { map_id: string; difficulty_id: string; access: string; status: string; trial_count: number; xp_per_minute: number | null; minimum_trial_rate: number | null; maximum_trial_rate: number | null; observation: string; unknowns?: string[] };
type Result = { routes: Route[]; best_measured_candidate: { map_id: string; difficulty_id: string } | null; retest_recommended: boolean; excluded_trials: { trial_id: string; reason: string; unknowns?: string[] }[] };
const rateLabel = (value: number | null) => value === null ? "未测量" :
  value > 0 && value < .005 ? value.toExponential(2) : value.toFixed(2);
type Props = { facts: Snapshot; revision: number; buildHash: string; onError: (message: string) => void };

export function RouteTrials({ facts, revision, buildHash, onError }: Props) {
  const [map, setMap] = useState("示例地图");
  const [difficulty, setDifficulty] = useState("normal");
  const [xp, setXp] = useState("100");
  const [seconds, setSeconds] = useState("60");
  const [bonus, setBonus] = useState("已确认无额外经验加成");
  const [kind, setKind] = useState("character");
  const [levelStart, setLevelStart] = useState(String(facts.character_level));
  const [levelEnd, setLevelEnd] = useState(String(facts.character_level));
  const [access, setAccess] = useState("active");
  const [consistent, setConsistent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ key: string; id: string }>();
  const [routes, setRoutes] = useState<{ map_id: string; difficulty_id: string; access: string }[]>([]);
  const [result, setResult] = useState<Result>();

  const minimumLevel = kind === "paragon" ? 0 : 1;
  const start = Number(levelStart);
  const end = Number(levelEnd);
  const rangeValid = Boolean(levelStart.trim() && levelEnd.trim() && isExactCount(levelStart)
    && isExactCount(levelEnd) && start >= minimumLevel && end >= start);
  const gainedXp = Number(xp);
  const elapsedSeconds = Number(seconds);
  const valid = Boolean(rangeValid && map.trim() && difficulty.trim() && bonus.trim()
    && xp.trim() && seconds.trim() && isExactCount(xp) && gainedXp >= 0
    && Number.isFinite(elapsedSeconds) && elapsedSeconds > 0);
  const scope = { context: facts.context, class_id: facts.class_id, build_hash: buildHash,
    bonuses_hash: bonus.trim(), objective: "leveling", level_start: start, level_end: end, xp_kind: kind };

  const invalidateDraft = () => { setResult(undefined); setConsistent(false); };
  const changeKind = (next: string) => {
    setKind(next);
    const initial = next === "character" ? String(facts.character_level) : "";
    setLevelStart(initial); setLevelEnd(initial);
    invalidateDraft();
  };
  const submit = async () => {
    if (busy || !revision || !consistent || !valid) return;
    setBusy(true);
    setResult(undefined);
    onError("");
    const body = { scope, map_id: map.trim(), difficulty_id: difficulty.trim(), access,
      xp_gain: gainedXp, complete_elapsed_seconds: elapsedSeconds, method: "cumulative_xp",
      bonuses_unchanged: consistent, build_unchanged: consistent, xp_transition: false,
      level_thresholds_verified: false, evidence_ids: ["manual-trial"] };
    const key = JSON.stringify(body);
    const request = pending?.key === key ? pending : { key, id: newId("trial") };
    setPending(request);
    try {
      const next = routes.filter(r => r.map_id !== body.map_id || r.difficulty_id !== body.difficulty_id);
      next.push({ map_id: body.map_id, difficulty_id: body.difficulty_id, access });
      await api("planning/trials", { trial_id: request.id, ...body });
      setRoutes(next);
      setResult(await api<Result>("planning/routes/compare", { scope, candidates: next }));
      setPending(undefined);
    } catch (e) { onError(e instanceof Error ? e.message : "试验记录未被接受。"); }
    finally { setBusy(false); }
  };
  const excludedScope = result?.excluded_trials.filter(trial => trial.reason === "incomparable_scope").length ?? 0;

  const excludedNumbers = result?.excluded_trials.filter(trial =>
    trial.unknowns?.includes("trial_measurement_out_of_range")).length ?? 0;
  const uncertainTotals = result?.routes.filter(route =>
    route.unknowns?.includes("aggregate_trial_measurement_out_of_range")).length ?? 0;

  return <section className="panel">
    <div className="section-heading"><div><span className="eyebrow">MEASURED ROUTES</span><h2>用实际试验比较练级路线</h2></div><span className="tag">已测候选</span></div>
    <p className="muted">记录实际累计获得的经验，以及包含移动、等待、恢复和死亡的完整耗时。升级时要累计整段经验，不能只减两次进度条数值。</p>
    <fieldset className="draft-controls" disabled={busy}>
      <div className="fields">
        <label>地图<input value={map} onChange={e => { setMap(e.target.value); invalidateDraft(); }}/></label>
        <label>难度<input value={difficulty} onChange={e => { setDifficulty(e.target.value); invalidateDraft(); }}/></label>
        <label>实际累计经验<input type="number" min="0" value={xp} onChange={e => { setXp(e.target.value); invalidateDraft(); }}/></label>
        <label>完整耗时（秒）<input type="number" min="0" step="any" value={seconds} onChange={e => { setSeconds(e.target.value); invalidateDraft(); }}/></label>
        <label>经验类型<select value={kind} onChange={e => changeKind(e.target.value)}><option value="character">角色经验</option><option value="paragon">巅峰经验</option></select></label>
        <label>入口状态<select value={access} onChange={e => { setAccess(e.target.value); invalidateDraft(); }}><option value="active">确认可进入</option><option value="inactive">确认不可进入</option><option value="unknown">入口未知</option></select></label>
        <label>试验起始等级<input type="number" min={minimumLevel} step="1" value={levelStart} onChange={e => { setLevelStart(e.target.value); invalidateDraft(); }}/></label>
        <label>试验结束等级<input type="number" min={minimumLevel} step="1" value={levelEnd} onChange={e => { setLevelEnd(e.target.value); invalidateDraft(); }}/></label>
      </div>
      <p className="muted">{kind === "paragon" ? "巅峰起止等级需单独填写，不能沿用角色等级。" : "填写这次试验实际跨越的角色等级范围。"}不同等级范围、经验类型、构筑或加成的试验分别比较。</p>
      {!rangeValid && <p className="warning" role="status">请填写有效的起止等级，结束等级不能低于起始等级。</p>}
      <label>经验加成记录<input value={bonus} onChange={e => { setBonus(e.target.value); invalidateDraft(); }}/></label>
      <label className="check"><input type="checkbox" checked={consistent} onChange={e => setConsistent(e.target.checked)}/>本次构筑和加成保持一致，没有跨越角色/巅峰经验转换。已核对起止等级和累计实际经验。</label>
      <button type="button" onClick={submit} disabled={busy || !revision || !consistent || !valid}>{busy ? "保存与比较中…" : "记录试验并比较"}</button>
    </fieldset>
    {result && <div aria-live="polite">
      <p className="muted">比较范围：{kind === "character" ? "角色" : "巅峰"}等级 {start} → {end}</p>
      <p>{result.best_measured_candidate ? "已测候选中最高：" + result.best_measured_candidate.map_id + " / " + result.best_measured_candidate.difficulty_id : "尚无可比较的测量，请先确认入口与试验条件。"}</p>
      <table><thead><tr><th>地图 / 难度</th><th>试验数</th><th>累计经验 / 完整分钟</th><th>状态</th></tr></thead><tbody>{result.routes.map(r => <tr key={JSON.stringify([r.map_id, r.difficulty_id])}><td>{r.map_id} / {r.difficulty_id}</td><td>{r.trial_count}</td><td>{rateLabel(r.xp_per_minute)}</td><td>{r.status === "measured" ? r.trial_count === 1 ? "单次试验" : "多次试验" : "待确认或未测量"}</td></tr>)}</tbody></table>
      {excludedScope > 0 && <p className="muted">已排除 {excludedScope} 条范围不一致的历史试验。</p>}
      {excludedNumbers > 0 && <p className="warning" role="status">已排除 {excludedNumbers} 条数值无法可靠计算的历史试验，请核对累计经验与完整耗时。</p>}
      {uncertainTotals > 0 && <p className="warning" role="status">有 {uncertainTotals} 条路线的累计测量超出可靠计算范围，保持待确认，不参与最高路线比较。</p>}
      {result.retest_recommended && <p className="warning">建议复测：试验少、结果接近或波动较大。</p>}
      <p className="muted">这仅比较当前确认范围内的已测候选，不能证明全局最优。</p>
    </div>}
  </section>;
}
