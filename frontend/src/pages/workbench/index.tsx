import { useEffect, useState } from "react";
import { CaptureObservationForm } from "../../features/capture-observation";
import type { CaptureObservation } from "../../features/capture-observation";
import { EquipmentEditor, ObservationFields, emptySnapshot, mapItemField } from "../../features/edit-equipment";
import { BuildEditor } from "../../features/edit-build";
import { ProfileLibrary } from "../../features/profile-library";
import { AcquisitionEvidence } from "../../features/acquisition-evidence";
import { RouteTrials } from "../../features/route-trials";
import { EvaluationHistory } from "../../features/evaluation-history";
import { EvaluationCard } from "../../entities/evaluation";
import { ConfirmSnapshot } from "../../features/confirm-snapshot";
import { api, newId } from "../../shared/api";
import type { Demo, EvaluationResult, Intent, Pack, Snapshot } from "../../shared/api";

const defaultIntent = (): Intent => ({ revision: 1, scenario: "leveling", required_capabilities: [], allowed_build_changes: [], future_builds: [], budget: {} });

export function Workbench() {
  const [facts, setFacts] = useState<Snapshot>(() => emptySnapshot());
  const [purpose, setPurpose] = useState<Intent>(defaultIntent);
  const [packs, setPacks] = useState<Pack[]>([]);
  const [selectedPack, setSelectedPack] = useState("");
  const [rawText, setRawText] = useState("");
  const [editor, setEditor] = useState(() => JSON.stringify(facts, null, 2));
  const [profileId, setProfileId] = useState(() => newId("profile"));
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
    api<{ packs: Pack[] }>("knowledge/packs").then(catalog => {
      if (!alive) return;
      setPacks(catalog.packs); setHealth("本地服务已连接");
    }).catch(e => { if (alive) { setError(e.message); setHealth("连接失败"); } });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const compatible = packs.filter(p => p.context.game_id === facts.context.game_id);
    if (!compatible.some(p => p.pack_id + "/" + p.version === selectedPack)) {
      const pack = compatible.at(-1);
      setSelectedPack(pack ? pack.pack_id + "/" + pack.version : "");
    }
  }, [packs, facts.context.game_id, selectedPack]);

  useEffect(() => {
    let alive = true;
    const check = () => api<{ degraded: boolean }>("status")
      .then(status => { if (alive) setHealth(status.degraded ? "本地服务降级 · 请重新启动桌面" : "本地服务已连接"); })
      .catch(() => { if (alive) setHealth("连接失败 · 请重新启动桌面"); });
    const timer = setInterval(check, 5000);
    return () => { alive = false; clearInterval(timer); };
  }, []);

  const changeFacts = (next: Snapshot) => {
    setFacts(next); setEditor(JSON.stringify(next, null, 2)); setConfirmed(false);
    setResult(undefined); setReplayed(false); setHistorical(false); setError("");
  };
  const invalidateCapture = () => {
    if (!captureObservation) return;
    setCaptureObservation(undefined); setConfirmed(false); setResult(undefined); setReplayed(false);
  };
  const replaceDraft = (next: Snapshot, intent = defaultIntent(), text = "") => {
    changeFacts(next); setPurpose(intent); setRawText(text); setCaptureObservation(undefined);
    setProfileId(newId("profile")); setRevision(0); setConfirmedHash(""); setEvaluationRequest(undefined);
  };
  const loadDemo = async () => {
    if (busy) return;
    setBusy(true); setError("");
    try { const demo = await api<Demo>("demo"); replaceDraft(demo.facts, demo.intent, demo.label); }
    catch (e) { setError(e instanceof Error ? e.message : "示例加载失败。"); }
    finally { setBusy(false); }
  };
  const applyEditor = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const parsed: unknown = JSON.parse(editor);
      await api("profile/snapshots/validate", { facts: parsed });
      changeFacts(parsed as Snapshot);
    } catch (e) { setError("构筑数据格式不完整，请检查必填字段。" + (e instanceof Error ? " " + e.message : "")); }
    finally { setBusy(false); }
  };
  const evaluate = async () => {
    if (!confirmed || busy) return;
    const pack = packs.find(p => p.pack_id + "/" + p.version === selectedPack);
    if (!pack) { setError("当前游戏没有可选知识包。档案可以先保存，其他游戏的规则不能混用。"); return; }
    setBusy(true); setError("");
    const key = JSON.stringify({ profileId, revision, selectedPack, purpose });
    const request = evaluationRequest?.key === key ? evaluationRequest : { key, id: newId("evaluation") };
    setEvaluationRequest(request);
    try {
      const output = await api<EvaluationResult>("evaluation/evaluations", { request_id: request.id, profile_id: profileId, profile_revision: revision, pack_id: pack.pack_id, pack_version: pack.version, pack_hash: pack.pack_hash, intent: purpose });
      setResult(output); setReplayed(false); setHistorical(false);
    } catch (e) { setError(e instanceof Error ? e.message : "评估失败。"); }
    finally { setBusy(false); }
  };
  const replay = async () => {
    if (!result || busy) return;
    setBusy(true); setReplaying(true); setError("");
    try { const response = await api<{ identical: boolean }>("evaluation/evaluations/" + result.evaluation_id + "/replay", {}); setReplayed(response.identical); }
    catch (e) { setError(e instanceof Error ? e.message : "回放失败。"); }
    finally { setReplaying(false); setBusy(false); }
  };
  const compatiblePacks = packs.filter(p => p.context.game_id === facts.context.game_id);
  const observationText = rawText.trim() || "手动核对录入：\n" + JSON.stringify(facts);
  const synthetic = facts.context.game_id === "lootweave-fixture";

  return <div className="shell">
    <aside className="sidebar"><a className="brand" href="/" aria-label="LootWeave 主页"><span className="brand-mark">L</span>LootWeave</a><span className="sidebar-label">装备决策</span><a className="nav active" href="#workbench">◈　装备工作台</a><span className="sidebar-label">本地档案</span><p className="sidebar-note">录入 → 核对 → 对比 → 回放<br/>所有处理留在本机。</p><div className="service-status"><span aria-hidden="true">●</span> {health}</div></aside>
    <main id="workbench"><header className="topbar"><span>工作台 / 换装比较</span><span className="tag">本地运行</span></header>
      <section className="intro"><span className="eyebrow">EQUIPMENT WORKBENCH</span><h1>每次换装，都有依据。</h1><p>录入候选装备和当前装备，先看实际词条变化，再核对构筑用途。</p></section>
      <div className="notice">{synthetic ? <><strong>当前使用合成示例。</strong>真实游戏规则尚未通过证据验收；未知版本和缺失机制会要求补充确认。</> : <><strong>从你的实际装备开始。</strong>可保存个人档案并比较物品字段；Deskrawl 的真实机制尚待验证，保留和换装结论会列出待确认依据。</>}</div>
      {error && <div className="error" role="alert">{error}</div>}
      <div className="draft-actions"><button type="button" disabled={busy} onClick={() => replaceDraft(emptySnapshot())}>新建真实录入</button><button type="button" disabled={busy} onClick={loadDemo}>加载合成示例</button></div>
      <ProfileLibrary busy={busy} refreshKey={profileId + "/" + revision} onBusyChange={setBusy} onError={setError} onOpen={profile => { setFacts(profile.facts); setEditor(JSON.stringify(profile.facts, null, 2)); setProfileId(profile.profile_id); setRevision(profile.revision); setConfirmedHash(profile.build_hash); setConfirmed(["verified", "not_recorded"].includes(profile.observation_time_status || "not_recorded")); setCaptureObservation(undefined); setRawText(""); setResult(undefined); setReplayed(false); setHistorical(false); setError(""); setPurpose(defaultIntent()); }}/>
      <fieldset className="draft-controls" disabled={busy}>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">01 · CONTEXT</span><h2>固定比较场景</h2></div><span className="tag">练级</span></div>
          <div className="fields"><label>游戏范围<input value={facts.context.game_id} onChange={e => changeFacts({ ...facts, context: { ...facts.context, game_id: e.target.value } })}/></label><label>职业<input value={facts.class_id} onChange={e => changeFacts({ ...facts, class_id: e.target.value })}/></label><label>构建版本<input value={facts.context.game_build} onChange={e => changeFacts({ ...facts, context: { ...facts.context, game_build: e.target.value } })}/></label><label>角色等级<input type="number" min="1" step="1" value={facts.character_level} onChange={e => changeFacts({ ...facts, character_level: Number(e.target.value) })}/></label><label>发行版本<input value={facts.context.edition} onChange={e => changeFacts({ ...facts, context: { ...facts.context, edition: e.target.value } })}/></label><label>模式<input value={facts.context.mode} onChange={e => changeFacts({ ...facts, context: { ...facts.context, mode: e.target.value } })}/></label><label>赛季<input value={facts.context.season} onChange={e => changeFacts({ ...facts, context: { ...facts.context, season: e.target.value } })}/></label><label>规则范围<input value={facts.context.ruleset_id} onChange={e => changeFacts({ ...facts, context: { ...facts.context, ruleset_id: e.target.value } })}/></label></div>
          <label>知识包版本<select value={selectedPack} onChange={e => { setSelectedPack(e.target.value); setResult(undefined); }}>{!compatiblePacks.length && <option value="">当前游戏暂无规则包</option>}{compatiblePacks.map(p => <option key={p.pack_id + p.version} value={p.pack_id + "/" + p.version}>{p.execution_policy === "synthetic_only" ? "合成机制示例" : "Deskrawl · 仅研究"} · {p.version}</option>)}</select></label>
          <p className="muted">版本不确定时保留 unknown。研究包提供的版本参考不会自动成为你的游戏版本。</p>
        </section>
        <EquipmentEditor facts={facts} onChange={changeFacts}/>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">04 · BUILD AND INTENT</span><h2>当前构筑与比较目标</h2></div></div>
          <BuildEditor facts={facts} intent={purpose} onFactsChange={changeFacts} onIntentChange={next => { setPurpose(next); setResult(undefined); setReplayed(false); }}/>
          <div className="fields conditions">{Object.entries(facts.conditions).map(([key, state]) => <label key={key}>{({ hero_cast: "角色本人施法", mana_starved: "法力成为瓶颈", survival_required: "需要生存机制", companion_present: "仆从可用", target_frozen: "目标已冻结", buff_active: "临时增益有效" } as Record<string, string>)[key] || key}<select value={state} onChange={e => changeFacts({ ...facts, conditions: { ...facts.conditions, [key]: e.target.value } })}><option value="active">已确认生效</option><option value="inactive">已确认未生效</option><option value="unknown">未知 · 需要确认</option></select></label>)}</div>
        </section>
        <section className="panel"><div className="section-heading"><div><span className="eyebrow">05 · CONFIRMATION</span><h2>核对输入与完整构筑</h2></div><span className="tag">{revision ? "快照 r" + revision : "尚未确认"}</span></div>
          <details><summary>从截图识别装备字段</summary><CaptureObservationForm gameId={facts.context.game_id} contextKey={JSON.stringify(facts.context)} onInvalidateCapture={invalidateCapture} onBusyChange={setBusy} onError={setError} onCaptured={observation => { const ms = observation.capture_context?.captured_at_ms; if (ms !== undefined && (!Number.isSafeInteger(ms) || ms <= 0 || ms > 253402300799999)) { setError("原始截图时间无效，请重新采集。"); return; } setCaptureObservation(observation); setRawText(observation.raw_text); const evidence = { id: newId("ocr-input"), kind: "ocr_confirmation", source_ref: "observation://" + observation.observation_id, captured_at: ms ? new Date(ms).toISOString() : facts.captured_at, verification: "confirmed", conflicts: [] }; changeFacts({ ...facts, evidence: [...facts.evidence, evidence], unknowns: [...new Set([...facts.unknowns, "ocr_fields_not_mapped"])] }); }}/>
          {captureObservation && <ObservationFields fields={captureObservation.fields} onApply={field => { const evidence = facts.evidence.find(e => e.source_ref === "observation://" + captureObservation.observation_id); if (evidence) changeFacts({ ...facts, candidate_item: mapItemField(facts.candidate_item, field, evidence.id, field.field === "level") }); }} onReviewed={() => changeFacts({ ...facts, unknowns: facts.unknowns.filter(x => x !== "ocr_fields_not_mapped") })}/>}</details>
          <label>原始文本<textarea rows={3} placeholder="可粘贴装备原文；手动录入时可留空。" value={rawText} onChange={e => { setRawText(e.target.value); setConfirmed(false); setResult(undefined); }}/></label>
          <p className="muted">未粘贴原文时，以你填写的字段作为手动录入依据。截图只提供装备字段，其他时点的构筑来源会保留原时间。</p>
          <details><summary>查看或编辑完整构筑数据</summary><p className="muted">高级输入可核对面板、嵌入物品、条件、时间与全部依据；未知内容请保留为未知。</p><textarea className="data-editor" rows={14} aria-label="完整构筑数据" value={editor} onChange={e => { setEditor(e.target.value); setConfirmed(false); setResult(undefined); }}/><button type="button" onClick={applyEditor}>应用构筑修改</button></details>
          <ConfirmSnapshot onBusyChange={setBusy} draftApplied={editor === JSON.stringify(facts, null, 2)} key={JSON.stringify(facts) + rawText + editor + (captureObservation?.observation_id ?? "text")} facts={facts} rawText={observationText} capture={captureObservation} profileId={profileId} revision={revision} onError={setError} onConfirmed={(nextRevision, confirmedFacts, factsHash) => { setConfirmedHash(factsHash); setRevision(nextRevision); setFacts(confirmedFacts); setEditor(JSON.stringify(confirmedFacts, null, 2)); setConfirmed(true); setResult(undefined); setError(""); }}/>
        </section>
      </fieldset>
      <div className="action-row"><p>{confirmed ? "✓ 输入已确认，可以比较完整配置。" : "请先核对并保存快照。"}</p><button type="button" className="primary" onClick={evaluate} disabled={!confirmed || busy || !selectedPack}>{busy ? "处理中…" : "解释保留价值与换装变化 →"}</button></div>
      {historical && result && <p className="notice">正在查看保存的冻结输入及其规则版本，不会替换当前编辑草稿。</p>}
      {result && <EvaluationCard result={result} onReplay={replay} replaying={replaying} replayed={replayed}/>}
      <EvaluationHistory disabled={busy} onBusyChange={setBusy} refreshKey={result?.evaluation_id || ""} onError={setError} onSelect={saved => { setResult(saved); setHistorical(true); setReplayed(false); }}/>
      <details><summary>路线试验与获取记录</summary><RouteTrials key={profileId + revision + String(confirmed)} facts={facts} revision={confirmed ? revision : 0} buildHash={confirmedHash} onError={setError}/><AcquisitionEvidence key={profileId + revision + String(confirmed) + selectedPack} facts={facts} revision={confirmed ? revision : 0} pack={packs.find(p => p.pack_id + "/" + p.version === selectedPack) || null} onError={setError}/></details>
      <footer className="page-footer">LootWeave · 个人资料保存在本机 · 每次比较固定档案和规则版本</footer>
    </main>
  </div>;
}
