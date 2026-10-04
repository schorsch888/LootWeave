import { useEffect, useState } from "react";
import { CaptureObservationForm } from "../../features/capture-observation";
import type { CaptureObservation } from "../../features/capture-observation";
import { AcquisitionEvidence } from "../../features/acquisition-evidence";
import { RouteTrials } from "../../features/route-trials";
import { EvaluationHistory } from "../../features/evaluation-history";
import { EvaluationCard } from "../../entities/evaluation";
import { ConfirmSnapshot } from "../../features/confirm-snapshot";
import { api, newId } from "../../shared/api";
import type { Demo, EvaluationResult, Intent, Pack, Snapshot } from "../../shared/api";

export function Workbench() {
  const [facts, setFacts] = useState<Snapshot>();
  const [purpose, setPurpose] = useState<Intent>();
  const [packs, setPacks] = useState<Pack[]>([]);
  const [selectedPack, setSelectedPack] = useState("");
  const [rawText, setRawText] = useState("合成示例：现有法杖提供冰冷技能配合与法力循环，和兜帽构成两件套。候选法杖提供 65 点活力。");
  const [editor, setEditor] = useState("");
  const [profileId] = useState(() => newId("profile"));
  const [revision, setRevision] = useState(0);
  const [confirmedHash, setConfirmedHash] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<EvaluationResult>();
  const [replaying, setReplaying] = useState(false);
  const [captureObservation, setCaptureObservation] = useState<CaptureObservation>();
  const [replayed, setReplayed] = useState(false);
  const [historical, setHistorical] = useState(false);
  const [health, setHealth] = useState("正在连接");
  const [evaluationRequest, setEvaluationRequest] = useState<{ key: string; id: string }>();

  useEffect(() => {
    let alive = true;
    Promise.all([api<Demo>("demo"), api<{ packs: Pack[] }>("knowledge/packs")]).then(([demo, catalog]) => {
      if (!alive) return;
      setFacts(demo.facts); setPurpose(demo.intent); setEditor(JSON.stringify(demo.facts, null, 2));
      setPacks(catalog.packs);
      const pack = catalog.packs.find(p => p.execution_policy === "synthetic_only");
      setSelectedPack(pack ? pack.pack_id + "/" + pack.version : "");
      setHealth("本地服务已连接");
    }).catch(e => { if (alive) { setError(e.message); setHealth("连接失败"); } });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const check = () => api<{ degraded: boolean; services: Record<string, { state: string }> }>("status")
      .then(status => setHealth(status.degraded ? "本地服务降级 · 请重新启动桌面" : "本地服务已连接"))
      .catch(() => setHealth("连接失败 · 请重新启动桌面"));
    const timer = setInterval(check, 5000);
    return () => clearInterval(timer);
  }, []);

  const changeFacts = (next: Snapshot) => {
    setFacts(next); setEditor(JSON.stringify(next, null, 2)); setConfirmed(false);
    setResult(undefined); setReplayed(false); setError("");
  };
  const invalidateCapture = () => {
    if (!captureObservation) return;
    setCaptureObservation(undefined); setConfirmed(false);
    setResult(undefined); setReplayed(false);
  };
  const applyEditor = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const parsed: unknown = JSON.parse(editor);
      if (!parsed || typeof parsed !== "object" || !("context" in parsed) || !("candidate_item" in parsed)) throw new Error();
      await api("profile/snapshots/validate", { facts: parsed });
      changeFacts(parsed as Snapshot);
    } catch { setError("构筑数据格式不完整，请保留全部字段并检查文本。"); }
    finally { setBusy(false); }
  };
  const evaluate = async () => {
    if (!facts || !purpose || !confirmed || busy) return;
    const pack = packs.find(p => p.pack_id + "/" + p.version === selectedPack);
    if (!pack) return;
    setBusy(true); setError("");
    const key = JSON.stringify({ profileId, revision, selectedPack, purpose });
    const request = evaluationRequest?.key === key ? evaluationRequest : { key, id: newId("evaluation") };
    setEvaluationRequest(request);
    try {
      const output = await api<EvaluationResult>("evaluation/evaluations", {
        request_id: request.id, profile_id: profileId, profile_revision: revision,
        pack_id: pack.pack_id, pack_version: pack.version, pack_hash: pack.pack_hash, intent: purpose,
      });
      setResult(output); setReplayed(false); setHistorical(false);
    } catch (e) { setError(e instanceof Error ? e.message : "评估失败。"); }
    finally { setBusy(false); }
  };
  const replay = async () => {
    if (!result) return;
    setReplaying(true); setError("");
    try {
      const response = await api<{ identical: boolean }>("evaluation/evaluations/" + result.evaluation_id + "/replay", {});
      setReplayed(response.identical);
    } catch (e) { setError(e instanceof Error ? e.message : "回放失败。"); }
    finally { setReplaying(false); }
  };

  return <div className="shell">
    <aside className="sidebar"><a className="brand" href="/" aria-label="LootWeave 主页"><span className="brand-mark">L</span>LootWeave</a><span className="sidebar-label">装备决策</span><a className="nav active" href="#workbench">◈　装备工作台</a><span className="sidebar-label">本地原型</span><p className="sidebar-note">输入 → 核对 → 快照 → 解释<br/>所有处理留在本机。</p><div className="service-status"><span aria-hidden="true">●</span> {health}</div></aside>
    <main id="workbench"><header className="topbar"><span>工作台 / 换装比较</span><span className="tag">本地运行 · 研究预览</span></header>
      <section className="intro"><span className="eyebrow">EQUIPMENT WORKBENCH</span><h1>每次换装，都有依据。</h1><p>把词条放回完整构筑中，分别解释当前用途、换装代价和未来价值。</p></section>
      <div className="notice"><strong>当前使用合成示例。</strong>真实游戏规则尚未通过证据验收；未知版本和缺失机制会要求补充确认。</div>
      {error && <div className="error" role="alert">{error}</div>}
      {!facts || !purpose ? <section className="panel" aria-live="polite">正在读取本地资料…</section> : <>
        <fieldset className="draft-controls" disabled={busy}>
        <div className="workspace-grid">
          <section className="panel"><div className="section-heading"><div><span className="eyebrow">01 · CONTEXT</span><h2>固定比较场景</h2></div><span className="tag">练级</span></div>
            <div className="fields"><label>游戏范围<input value={facts.context.game_id} onChange={e => changeFacts({ ...facts, context: { ...facts.context, game_id: e.target.value } })}/></label><label>构建版本<input value={facts.context.game_build} onChange={e => changeFacts({ ...facts, context: { ...facts.context, game_build: e.target.value } })}/></label><label>职业<input value={facts.class_id} onChange={e => changeFacts({ ...facts, class_id: e.target.value })}/></label><label>角色等级<input type="number" min="1" value={facts.character_level} onChange={e => changeFacts({ ...facts, character_level: Number(e.target.value) })}/></label></div>
            <label>知识包版本<select value={selectedPack} onChange={e => { setSelectedPack(e.target.value); setResult(undefined); }}>{packs.map(p => <option key={p.pack_id + p.version} value={p.pack_id + "/" + p.version}>{p.execution_policy === "synthetic_only" ? "合成机制示例" : "Deskrawl · 仅研究"} · {p.version}</option>)}</select></label>
            <p className="muted">只比较已明确的游戏、版本、模式和用途。</p>
          </section>
          <section className="panel"><div className="section-heading"><div><span className="eyebrow">02 · ITEM INSTANCE</span><h2>候选物品</h2></div><span className="tag">{facts.candidate_item.slot}</span></div><h3 className="item-name">{facts.candidate_item.name || facts.candidate_item.instance_id}</h3><p className="muted">替换 {facts.equipped_items[facts.candidate_item.slot]?.name || "空装备位"}</p><div className="affix-list">{facts.candidate_item.affixes.map((a, i) => <label key={a.id}><span>{a.id === "fixture-vitality" ? "示例活力" : a.id}</span><input type="number" value={a.value} onChange={e => { const next = structuredClone(facts); next.candidate_item.affixes[i].value = Number(e.target.value); changeFacts(next); }}/><small>{a.unit}</small></label>)}</div><label>库存覆盖<select value={facts.inventory_coverage} onChange={e => changeFacts({ ...facts, inventory_coverage: e.target.value })}><option value="complete">完整核对</option><option value="partial">部分核对</option><option value="unknown">尚不清楚</option></select></label><p className="muted">这是具体实例的实际值，不是图鉴模板。</p></section>
        </div>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">03 · CONFIRMATION</span><h2>核对输入与完整构筑</h2></div><span className="tag">{revision ? "快照 r" + revision : "尚未确认"}</span></div>
          <CaptureObservationForm gameId={facts.context.game_id} contextKey={JSON.stringify(facts.context)} onInvalidateCapture={invalidateCapture} onBusyChange={setBusy} onError={setError} onCaptured={observation => { setCaptureObservation(observation); setRawText(observation.raw_text); changeFacts({ ...facts, unknowns: [...new Set([...facts.unknowns, "ocr_fields_not_mapped"])] }); setConfirmed(false); setResult(undefined); }}/>
          {captureObservation && <p className="muted">已保留原始区域与识别原文；字段仍需逐项核对。{captureObservation.fields.map(f => f.field + "：" + (f.value ?? "未知") + " " + (f.unit ?? "未知单位")).join(" · ")}</p>}
          <label>原始文本<textarea rows={3} value={rawText} onChange={e => { setRawText(e.target.value); setConfirmed(false); setResult(undefined); }}/></label>
          <div className="build-strip"><span>技能 <strong>{facts.skills.map(s => s.id.replace("fixture-", "")).join("、") || "未选定"}</strong></span><span>天赋 <strong>{facts.talents.length}</strong></span><span>巅峰 <strong>{facts.paragon.length}</strong></span><span>符文 <strong>{facts.runes.length}</strong></span><span>仆从 <strong>{facts.companions.length}</strong></span></div>
          <div className="fields conditions">{Object.entries(facts.conditions).map(([key, state]) => <label key={key}>{({ hero_cast: "角色本人施法", mana_starved: "法力成为瓶颈", survival_required: "需要生存机制", companion_present: "仆从可用", target_frozen: "目标已冻结", buff_active: "临时增益有效" } as Record<string, string>)[key] || key}<select value={state} onChange={e => changeFacts({ ...facts, conditions: { ...facts.conditions, [key]: e.target.value } })}><option value="active">已确认生效</option><option value="inactive">已确认未生效</option><option value="unknown">未知 · 需要确认</option></select></label>)}</div>
          <details><summary>查看或编辑完整构筑数据</summary><p className="muted">原型支持核对全部实例、技能、天赋、巅峰、符文、仆从、时间与依据。未知内容请保留为未知。</p><textarea className="data-editor" rows={14} aria-label="完整构筑数据" value={editor} onChange={e => { setEditor(e.target.value); setConfirmed(false); setResult(undefined); }}/><button type="button" onClick={applyEditor}>应用构筑修改</button></details>
          <ConfirmSnapshot onBusyChange={setBusy} draftApplied={editor === JSON.stringify(facts, null, 2)} key={JSON.stringify(facts) + rawText + editor + (captureObservation?.observation_id ?? "text")} facts={facts} rawText={rawText} capture={captureObservation} profileId={profileId} revision={revision} onError={setError} onConfirmed={(nextRevision, confirmedFacts, factsHash) => { setConfirmedHash(factsHash); setRevision(nextRevision); setFacts(confirmedFacts); setEditor(JSON.stringify(confirmedFacts, null, 2)); setConfirmed(true); setResult(undefined); setError(""); }}/>
        </section>
        </fieldset>
        <div className="action-row"><p>{confirmed ? "✓ 输入已确认，可以比较完整配置。" : "请先核对并保存快照。"}</p><button type="button" className="primary" onClick={evaluate} disabled={!confirmed || busy}>{busy ? "正在重算完整配置…" : "解释保留价值与换装变化 →"}</button></div>
        <RouteTrials key={profileId + revision + String(confirmed)} facts={facts} revision={confirmed ? revision : 0} buildHash={confirmedHash} onError={setError}/>
        <AcquisitionEvidence key={profileId + revision + String(confirmed) + selectedPack} facts={facts} revision={confirmed ? revision : 0} pack={packs.find(p => p.pack_id + "/" + p.version === selectedPack) ?? null} onError={setError}/>
        <EvaluationHistory refreshKey={result?.evaluation_id ?? ""} onError={setError} onSelect={stored => { setResult(stored); setHistorical(true); setReplayed(false); setError(""); }}/>
        {result && historical && <p className="notice">正在查看保存的冻结输入及其规则版本，结果不使用当前草稿。</p>}
        {result && <EvaluationCard result={result} onReplay={replay} replaying={replaying} replayed={replayed}/>}
      </>}
      <footer className="page-footer">LootWeave · 用证据解释，不让未知变成结论。</footer>
    </main>
  </div>;
}
