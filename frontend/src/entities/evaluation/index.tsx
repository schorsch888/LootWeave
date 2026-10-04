import type { EvaluationResult } from "../../shared/api";

const retention: Record<string, string> = { keep: "建议保留", candidate: "未来构筑候选", low_current_relevance: "当前相关性低", needs_confirmation: "需要补充确认" };
const status: Record<string, string> = { blocked: "比较受阻", mechanism_loss: "换装会丢失机制", mechanism_change: "机制发生变化", no_known_change: "未发现已知机制变化" };
const capabilities: Record<string, string> = { archive_shield: "两件套防护", cold_focus: "冰冷技能配合", mana_loop: "法力循环", vitality_support: "活力支持", frost_cycle: "符文循环", resource_efficiency: "资源效率", survival: "生存依赖", temporary_focus: "临时专注", companion_support: "仆从支持", frozen_bonus: "冻结目标条件", fire_focus: "火焰技能配合" };
const label = (value: string) => capabilities[value] || value;
const owners: Record<string, string> = { hero: "角色", companion: "仆从" };
const mechanismStates: Record<string, string> = { active: "已确认生效", inactive: "已确认未生效", unknown: "未知 · 待确认" };
const unknownRequirement = "unknown_required_capability:";
const blockerLabel = (value: string) => value.startsWith(unknownRequirement)
  ? "该版本知识包尚未收录所需机制：" + value.slice(unknownRequirement.length) + "，暂不能判断其适用性。" : value;
const mechanismLabel = (capability: string, actor?: string) => actor ? (owners[actor] || actor) + " · " + label(capability) : label(capability);

export function EvaluationCard({ result, onReplay, replaying, replayed }: { result: EvaluationResult; onReplay: () => void; replaying: boolean; replayed: boolean }) {
  const lost = result.comparison.lost_mechanisms?.map(x => mechanismLabel(x.capability, x.actor))
    ?? result.comparison.lost_capabilities.map(label);
  const gained = result.comparison.gained_mechanisms?.map(x => mechanismLabel(x.capability, x.actor))
    ?? result.comparison.gained_capabilities.map(label);
  const missing = result.comparison.missing_mechanisms?.map(x => mechanismLabel(x.capability, x.actor))
    ?? result.comparison.missing_requirements.map(label);
  const uncertain = result.comparison.uncertain_mechanisms || [];
  return <section className="panel result" aria-labelledby="result-title">
    <div className="section-heading"><div><span className="eyebrow">DECISION RECORD</span><h2 id="result-title">{retention[result.retention] || result.retention}</h2></div><span className="tag">快照 r{result.pin.profile_revision}</span></div>
    <p className="notice">这是合成机制验证结果，尚不代表已验证的游戏建议或 DPS。</p>
    <div className="verdict"><strong>{status[result.comparison.status] || result.comparison.status}</strong><span>保留价值与立即换装分别判断</span></div>
    {result.comparison.scope_compatible === false ? <p className="warning">范围或版本不匹配，暂不能比较机制。</p> : <div className="delta-grid">
      <div><h3>换装失去</h3>{lost.length ? <ul>{lost.map(x => <li key={x}>{x}</li>)}</ul> : <p>未发现已知机制损失</p>}</div>
      <div><h3>换装获得</h3>{gained.length ? <ul>{gained.map(x => <li key={x}>{x}</li>)}</ul> : <p>未发现已知机制增益</p>}</div>
    </div>}
    {missing.length > 0 && <p className="warning">未满足所需机制：{missing.join("、")}</p>}
    {uncertain.length > 0 && <div className="warning"><strong>机制状态待确认</strong><ul>{uncertain.map(x => <li key={x.actor + ":" + x.capability}>{mechanismLabel(x.capability, x.actor)}：替换前 {mechanismStates[x.before]} → 替换后 {mechanismStates[x.after]}</li>)}</ul><p>请核对条件和来源后再判断。</p></div>}
    {result.comparison.equip_blockers.map(x => <p className="warning" key={x}>{x === "required_level_not_met" ? "尚未达到穿戴等级；仍可保留。" : "职业穿戴要求不满足。"}</p>)}
    {result.blockers.length > 0 && <details open><summary>缺失依据与待确认项（{result.blockers.length}）</summary><ul>{result.blockers.map(x => <li key={x}>{blockerLabel(x)}</li>)}</ul></details>}
    {result.reasons.length > 0 && <h3>用途说明与依据</h3>}
    {result.reasons.map((r, i) => <div className="reason" key={i}><strong>{r.capability ? mechanismLabel(r.capability, r.actor) : "当前用途"}</strong><p>{r.kind === "future_use" ? "在明确选择的未来构筑中存在用途；配套可行性：" + r.feasibility : r.kind === "low_current_relevance" ? "未发现已知的当前或选定未来用途；其他用途仍可能存在。" : "在当前确认条件下，这件物品提供此机制。"} </p><small>规则依据：{r.evidence_ids.join("、") || "无适用规则"} · 输入依据：{r.input_evidence_ids.join("、")}</small></div>)}
    <details><summary>完整配置与依据</summary><table><thead><tr><th>机制</th><th>归属</th><th>替换前</th><th>替换后</th><th>来源</th></tr></thead><tbody>{result.comparison.after.map(r => <tr key={r.rule_id}><td>{label(r.capability || "")}</td><td>{owners[r.actor || ""] || "归属未知"}</td><td>{result.comparison.before.find(x => x.rule_id === r.rule_id)?.state}</td><td>{r.state}</td><td>{r.source_ids?.join("、") || "无"}</td></tr>)}</tbody></table></details>
    <footer className="result-footer"><span>规则包 {result.pin.pack_version} · 评估器 {result.pin.evaluator_version} · 意图 r{result.pin.intent_revision}</span><button type="button" onClick={onReplay} disabled={replaying}>{replaying ? "回放中…" : replayed ? "✓ 回放一致 · 再次验证" : "回放验证"}</button></footer>
  </section>;
}
