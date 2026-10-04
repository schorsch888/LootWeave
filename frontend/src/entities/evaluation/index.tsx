import type { EvaluationResult } from "../../shared/api";

const retention: Record<string, string> = { keep: "建议保留", candidate: "未来构筑候选", low_current_relevance: "当前相关性低", needs_confirmation: "需要补充确认" };
const status: Record<string, string> = { blocked: "比较受阻", mechanism_loss: "换装会丢失机制", mechanism_change: "机制发生变化", no_known_change: "未发现已知机制变化" };
const capabilities: Record<string, string> = { archive_shield: "两件套防护", cold_focus: "冰冷技能配合", mana_loop: "法力循环", vitality_support: "活力支持", frost_cycle: "符文循环", resource_efficiency: "资源效率", survival: "生存依赖", temporary_focus: "临时专注", companion_support: "仆从支持", frozen_bonus: "冻结目标条件", fire_focus: "火焰技能配合" };
const label = (value: string) => capabilities[value] || value;
const owners: Record<string, string> = { hero: "角色", companion: "仆从" };
const mechanismStates: Record<string, string> = { active: "已确认生效", inactive: "已确认未生效", unknown: "未知 · 待确认" };
const unknownRequirement = "unknown_required_capability:";
const blockerNames: Record<string, string> = { game_mechanics_not_accepted: "真实游戏机制尚未验证，当前只比较已确认的物品字段。", inventory_not_fully_scanned: "库存尚未完整核对，不能判断全部未来用途。", cross_time_snapshot: "存在其他时点的来源，请核对同一时点的构筑。", "input_unknown:build_not_reviewed": "当前构筑尚未完整核对。", "input_unknown:current_slot_not_reviewed": "当前同槽装备尚未核对。", "input_unknown:ocr_fields_not_mapped": "请逐项核对截图识别字段。" };
const blockerLabel = (value: string) => blockerNames[value] || (value.startsWith(unknownRequirement)
  ? "该版本知识包尚未收录所需机制：" + value.slice(unknownRequirement.length) + "，暂不能判断其适用性。"
  : value.startsWith("unknown_affix_or_unit:") ? "尚无此词条的机制或单位规则：" + value.split(":")[1]
  : value.startsWith("unknown_context:") ? "游戏范围仍待确认：" + value.split(":")[1]
  : value.startsWith("incompatible_context:") ? "知识包与实际游戏范围不同：" + value.split(":")[1]
  : value.startsWith("required_level_unknown:") ? "穿戴等级待确认：" + value.split(":")[1]
  : value.startsWith("item_modifications_unknown:") ? "强化或插槽状态待确认：" + value.split(":")[1]
  : value === "item_unknown:effects_not_reviewed" ? "物品特殊效果尚未核对。" : value);
const statNames: Record<string, string> = { vitality: "活力", armor: "护甲", strength: "力量", dexterity: "敏捷", intelligence: "智力", max_health: "最大生命", max_mana: "最大法力", attack_speed: "攻击速度", critical_chance: "暴击率", critical_damage: "暴击伤害", fire_damage: "火焰伤害", cold_damage: "冰冷伤害", lightning_damage: "闪电伤害", physical_damage: "物理伤害", "fixture-vitality": "示例活力", "fixture-cold-bonus": "示例冰冷加成" };
const units: Record<string, string> = { points: "点", percent: "%", percent_points: "百分点", seconds: "秒", per_second: "每秒" };
const rollStates: Record<string, string> = { comparable: "同词条、同单位", added: "仅候选物品有记录", removed: "仅当前物品有记录", unit_mismatch: "单位不同，未相减", out_of_range: "差值超出可靠范围" };
const rollValue = (value: number | null, unit: string | null) => value === null ? "未提供" : value + " " + (units[unit || ""] || unit || "");
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
    <p className="notice">{result.pin.context.game_id === "lootweave-fixture" ? "这是合成机制验证结果，尚不代表已验证的游戏建议或 DPS。" : "下方显示已确认物品的字段差异；真实游戏机制和 DPS 尚未验证。"}</p>
    {result.comparison.item_rolls && <div className="roll-delta"><h3>实际词条对比</h3><p className="muted">{result.comparison.item_rolls.current_item?.name || "当前槽位无物品记录"} → {result.comparison.item_rolls.candidate_item.name || "候选物品"}。仅比较物品字段；缺失值保留为未知，不作为零值。</p>
      {result.comparison.item_rolls.rows.length ? <table><thead><tr><th>词条</th><th>当前物品</th><th>候选物品</th><th>差值</th><th>核对状态</th></tr></thead><tbody>{result.comparison.item_rolls.rows.map(row => <tr key={row.affix_id}><td>{statNames[row.affix_id] || row.affix_id}</td><td>{rollValue(row.current_value, row.current_unit)}</td><td>{rollValue(row.candidate_value, row.candidate_unit)}</td><td>{row.delta === null ? "—" : (row.delta > 0 ? "+" : "") + row.delta + (row.current_unit === "percent" || row.current_unit === "percent_points" ? " 百分点" : " " + (units[row.current_unit || ""] || row.current_unit || ""))}</td><td>{rollStates[row.status] || row.status}</td></tr>)}</tbody></table> : <p className="muted">尚无实际词条，请在装备表单中录入。</p>}
      <p className="muted">差值不代表 DPS 或提升比例，特殊效果、套装与完整构筑需要另外核对。</p>
    </div>}
    <div className="verdict"><strong>{status[result.comparison.status] || result.comparison.status}</strong><span>保留价值与立即换装分别判断</span></div>
    {result.comparison.scope_compatible === false ? <p className="warning">游戏机制尚未验证，或范围、版本不匹配；物品字段差异仍可查看。</p> : <div className="delta-grid">
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
