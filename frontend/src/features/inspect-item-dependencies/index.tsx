import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/api";
import type { ItemDependencyResult, Pack, Snapshot } from "../../shared/api";

const names: Record<string, string> = { LegendaryStaff1: "霜龙法杖", SorcererBasicAttack2: "冰碎片" };
const unknowns: Record<string, string> = {
  runtime_equipment_events: "穿戴、卸下与重载时的实际触发流程",
  actor_context_overrides: "作用角色与上下文覆盖",
  legal_stacking: "重复来源与合法叠加",
  target_collision_damage: "目标资格、碰撞与实际伤害",
  online_overrides: "当前线上服务端覆盖与观测一致性",
};

export function ItemDependencies({ facts, pack, ready }: { facts: Snapshot; pack: Pack | null; ready: boolean }) {
  const [template, setTemplate] = useState("");
  const [result, setResult] = useState<ItemDependencyResult>();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    if (!ready) { request.current?.abort(); setResult(undefined); setBusy(false); }
    return () => { request.current?.abort(); request.current = null; };
  }, [ready]);

  const query = async () => {
    if (!ready || !pack || !template || request.current) return;
    const controller = new AbortController();
    request.current = controller;
    setBusy(true); setError(""); setResult(undefined);
    try {
      const response = await api<ItemDependencyResult>("knowledge/item-dependencies", {
        pack_id: pack.pack_id, pack_version: pack.version, pack_hash: pack.pack_hash,
        context: facts.context, class_id: facts.class_id, template_id: template,
      }, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (response.contract_version !== 1 || response.record_kind !== "item_template_dependency" ||
          response.scope !== "reviewed_static_only" || response.mechanics_accepted !== false ||
          response.pack_id !== pack.pack_id || response.pack_version !== pack.version ||
          response.pack_hash !== pack.pack_hash || response.class_id !== facts.class_id ||
          response.dependency.status !== "reviewed_static_only" || response.dependency.template_id !== template) {
        throw new Error("返回资料与当前选择不一致，请重新查询。");
      }
      setResult(response);
    } catch (e) {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "依赖资料读取失败，请重试。");
    } finally {
      if (request.current === controller) request.current = null;
      if (!controller.signal.aborted) setBusy(false);
    }
  };

  return <section className="panel item-dependency" aria-label="候选装备依赖资料">
    <div className="section-heading"><h2>候选装备依赖资料</h2><span className="tag">静态关联</span></div>
    <p>当前候选：{facts.candidate_item.name || facts.candidate_item.instance_id || "尚未录入"}</p>
    <p className="muted">请明确选择对应模板。装备名称和识别文字不会自动确认模板或线上机制。</p>
    {pack && <p className="muted">资料版本 {pack.version} · {pack.context.edition} · 构建 {pack.context.game_build} · {pack.context.mode === "online" ? "线上模式" : pack.context.mode}</p>}
    {!pack?.dependency_templates?.length ? <p className="muted">当前知识包尚未提供装备依赖资料。</p> : <>
      <label>候选装备资料模板<select aria-label="候选装备资料模板" value={template} disabled={!ready || busy} onChange={e => { setTemplate(e.target.value); setResult(undefined); setError(""); }}>
        <option value="">请选择已核对的装备模板</option>
        {pack.dependency_templates.map(item => <option key={item.template_id} value={item.template_id}>{names[item.template_id] || item.label}</option>)}
      </select></label>
      <button type="button" disabled={!ready || busy || !template} onClick={() => void query()}>{busy ? "正在读取依赖资料…" : "查询候选依赖"}</button>
    </>}
    {!ready && <p role="status">等待知识包服务与资料目录就绪…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {result && <div aria-live="polite">
      <h3>{names[result.dependency.template_id] || result.dependency.template_name} → 客户端装备效果 → {names[result.dependency.ability_id] || result.dependency.ability_name}</h3>
      <p className="warning">静态关联 · 在线条件待核验</p>
      <p>该资料记录客户端对象间的关联。实际触发、命中与伤害仍需核验。</p>
      <h3>仍需核验</h3>
      <ul>{result.dependency.unknowns.map(value => <li key={value}>{unknowns[value] || value}</li>)}</ul>
      <details><summary>查看来源与对象关联</summary>
        <p>知识包 {result.pack_version} · 构建 {result.context.game_build}</p>
        <table><thead><tr><th>来源对象</th><th>关联</th><th>目标对象</th></tr></thead><tbody>{result.dependency.object_links.map(link => <tr key={link.source_id + link.relation + link.target_id}><td>{link.source_id}</td><td>{link.relation === "equipment_effect" ? "装备效果" : "关联技能"}</td><td>{link.target_id}</td></tr>)}</tbody></table>
        {result.evidence.map(item => <article className="reason" key={item.id}><p>{item.source_ref}</p><p>来源构建：{item.source_build}</p><p>{item.results}</p><p className="muted">待核验：{item.unknowns}</p></article>)}
      </details>
    </div>}
  </section>;
}
