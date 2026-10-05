import { sourceGroups, sourceKinds } from "../../shared/build-sources";
import type { EvaluationComparison, EvaluationResult } from "../../shared/api";
import { slots } from "../../shared/equipment-labels";

const retention: Record<string, string> = { keep: "建议保留", candidate: "未来构筑候选", low_current_relevance: "当前相关性低", needs_confirmation: "需要补充确认" };
const status: Record<string, string> = { blocked: "比较受阻", mechanism_loss: "换装会丢失机制", mechanism_change: "机制发生变化", no_known_change: "未发现已知机制变化" };
const capabilities: Record<string, string> = { archive_shield: "两件套防护", cold_focus: "冰冷技能配合", mana_loop: "法力循环", vitality_support: "活力支持", frost_cycle: "符文循环", resource_efficiency: "资源效率", survival: "生存依赖", temporary_focus: "临时专注", companion_support: "仆从支持", frozen_bonus: "冻结目标条件", fire_focus: "火焰技能配合" };
const label = (value: string) => capabilities[value] || value;
const feasibility: Record<string, string> = { owned: "已拥有", obtainable: "可获取", hypothetical: "假设构筑" };
const owners: Record<string, string> = { hero: "角色", companion: "仆从" };
const mechanismStates: Record<string, string> = { active: "已确认生效", inactive: "已确认未生效", unknown: "未知 · 待确认" };
const unknownRequirement = "unknown_required_capability:";
const blockerNames: Record<string, string> = { game_mechanics_not_accepted: "真实游戏机制尚未验证，当前只比较已确认的物品字段。", inventory_not_fully_scanned: "库存尚未完整核对，不能判断全部未来用途。", inventory_not_recorded: "此快照尚未记录库存；请核对后保存，缺少记录不等于空库存。", future_build_change_not_permitted: "所选未来组合包含未允许的构筑更改。", candidate_class_incompatible: "候选装备不适用于当前职业；当前场景不能给出构筑用途结论。", cross_time_snapshot: "存在其他时点的来源，请核对同一时点的构筑。", "input_unknown:build_not_reviewed": "当前构筑尚未完整核对。", "input_unknown:current_slot_not_reviewed": "当前同槽装备尚未核对。", "input_unknown:ocr_fields_not_mapped": "请逐项核对截图识别字段。" };
const preparationBlockers: Record<string, string> = {
  unknown_condition: "机制的条件或作用者归属尚未确认", unknown_future_condition: "未来机制的条件或作用者归属尚未确认",
  future_source_not_recorded: "未来来源或预计状态尚未记录", future_source_removal_not_recorded: "撤销当前来源的条件和费用尚未记录",
  preparation_source_selection_conflict: "方案预计状态与未来来源选择不一致", preparation_source_owner_conflict: "方案的作用者或仆从归属发生变化",
  preparation_companion_not_recorded: "条件对应的仆从尚未记录", preparation_companion_not_selected: "方案所依赖的仆从未选入未来配置",
  preparation_option_not_recorded: "准备方案未记录", preparation_evidence_unconfirmed: "方案依据存在冲突或来自其他时点",
  preparation_scope_mismatch: "方案的游戏版本、模式或职业已变化", preparation_unknown: "准备方案仍有不确定项",
  preparation_target_conflict: "同一目标选择了多个互相冲突的方案", preparation_unlock_unknown: "学习或改造条件尚未确认",
  preparation_unlock_not_met: "尚未解锁学习或改造条件", preparation_level_unknown: "操作等级要求尚未确认",
  preparation_level_not_met: "角色等级未达到操作要求", preparation_input_changed: "原物品或构筑来源已变化，需要重新核对方案",
  preparation_skill_selection_conflict: "方案目标技能与未来构筑选择不一致", preparation_rank_limit_unknown: "技能等级上限尚未确认",
  preparation_rank_not_met: "目标技能等级超过已确认上限", preparation_companion_requirements_unknown: "具体仆从的归属、实际等级或专属条件尚未确认",
  preparation_item_not_selected: "改造目标物品尚未选入未来配套", preparation_outcome_unknown: "预计改后属性存在未知或随机结果",
  preparation_cost_unknown: "准备方案的全部费用尚未确认", future_skill_not_recorded: "未来技能的等级和来源尚未记录",
  future_skill_removal_not_recorded: "撤销原技能的条件和费用尚未记录", preparation_cost_out_of_range: "合计费用超出可靠整数范围",
  preparation_resource_unknown: "相关材料或货币数量尚未核对", preparation_resource_insufficient: "持有材料或货币不足",
  preparation_budget_exceeded: "合计费用超过本次预算", future_required_level_unknown: "所选配套物品的穿戴等级尚未确认",
};
const blockerLabel = (value: string) => preparationBlockers[value.split(":")[0]]
  ? preparationBlockers[value.split(":")[0]] + "：" + value.split(":").slice(1).join(" · ")
  : blockerNames[value] || (value.startsWith(unknownRequirement)
  ? "该版本知识包尚未收录所需机制：" + value.slice(unknownRequirement.length) + "，暂不能判断其适用性。"
  : value.startsWith("unknown_affix_or_unit:") ? "尚无此词条的机制或单位规则：" + value.split(":")[1]
  : value.startsWith("unknown_context:") ? "游戏范围仍待确认：" + value.split(":")[1]
  : value.startsWith("incompatible_context:") ? "知识包与实际游戏范围不同：" + value.split(":")[1]
  : value.startsWith("required_level_unknown:") ? "穿戴等级待确认：" + value.split(":")[1]
  : value.startsWith("item_modifications_unknown:") ? "强化或插槽状态待确认：" + value.split(":")[1]
  : value.startsWith("future_item_not_owned:") ? "配套物品不在当前持有记录中，请重新选择：" + value.split(":")[1]
  : value.startsWith("future_equipment_slot_conflict:") ? "未来组合中同一槽位选择了多件装备：" + (slots[value.split(":")[1]] || value.split(":")[1])
  : value.startsWith("future_candidate_slot_conflict:") ? "未来配套装备会替换正在比较的候选物品，请重新选择。"
  : value.startsWith("future_required_level_not_met:") ? "所选配套装备尚未达到穿戴等级：" + value.split(":")[1]
  : value.startsWith("future_item_class_incompatible:") ? "所选配套装备不适用于当前职业：" + value.split(":")[1]
  : value === "item_unknown:effects_not_reviewed" ? "物品特殊效果尚未核对。" : value);
const statNames: Record<string, string> = { vitality: "活力", armor: "护甲", strength: "力量", dexterity: "敏捷", intelligence: "智力", max_health: "最大生命", max_mana: "最大法力", attack_speed: "攻击速度", critical_chance: "暴击率", critical_damage: "暴击伤害", fire_damage: "火焰伤害", cold_damage: "冰冷伤害", lightning_damage: "闪电伤害", physical_damage: "物理伤害", "fixture-vitality": "示例活力", "fixture-cold-bonus": "示例冰冷加成" };
const units: Record<string, string> = { points: "点", percent: "%", percent_points: "百分点", seconds: "秒", per_second: "每秒" };
const rollStates: Record<string, string> = { comparable: "同词条、同单位", added: "仅候选物品有记录", removed: "仅当前物品有记录", unit_mismatch: "单位不同，未相减", out_of_range: "差值超出可靠范围" };
const rollValue = (value: number | null, unit: string | null) => value === null ? "未提供" : value + " " + (units[unit || ""] || unit || "");
const mechanismLabel = (capability: string, actor?: string) => actor ? (owners[actor] || actor) + " · " + label(capability) : label(capability);

function MechanismChanges({ comparison, future = false }: { comparison: EvaluationComparison; future?: boolean }) {
  if (future && comparison.status === "blocked" && !comparison.after.length)
    return <p className="warning">完整未来配置尚待核对，暂不判断机制得失。</p>;
  const lost = comparison.lost_mechanisms?.map(x => mechanismLabel(x.capability, x.actor)) ?? comparison.lost_capabilities.map(label);
  const gained = comparison.gained_mechanisms?.map(x => mechanismLabel(x.capability, x.actor)) ?? comparison.gained_capabilities.map(label);
  const missing = comparison.missing_mechanisms?.map(x => mechanismLabel(x.capability, x.actor)) ?? comparison.missing_requirements.map(label);
  const uncertain = comparison.uncertain_mechanisms ?? [];
  return <>
    {comparison.scope_compatible === false ? <p className="warning">游戏机制尚未验证，或范围、版本不匹配；物品字段差异仍可查看。</p> : <div className="delta-grid">
      <div><h3>{future ? "计划失去" : "换装失去"}</h3>{lost.length ? <ul>{lost.map(x => <li key={x}>{x}</li>)}</ul> : <p>未发现已知机制损失</p>}</div>
      <div><h3>{future ? "计划获得" : "换装获得"}</h3>{gained.length ? <ul>{gained.map(x => <li key={x}>{x}</li>)}</ul> : <p>未发现已知机制增益</p>}</div>
    </div>}
    {missing.length > 0 && <p className="warning">{future ? "未来配置未满足所需机制：" : "未满足所需机制："}{missing.join("、")}</p>}
    {uncertain.length > 0 && <div className="warning"><strong>{future ? "计划机制状态待确认" : "机制状态待确认"}</strong><ul>{uncertain.map(x => <li key={x.actor + ":" + x.capability}>{mechanismLabel(x.capability, x.actor)}：{future ? "当前" : "替换前"} {mechanismStates[x.before]} → {future ? "未来" : "替换后"} {mechanismStates[x.after]}</li>)}</ul><p>请核对条件和来源后再判断。</p></div>}
  </>;
}

export function EvaluationCard({ result, onReplay, replaying, replayed }: { result: EvaluationResult; onReplay: () => void; replaying: boolean; replayed: boolean }) {
  return <section className="panel result" aria-labelledby="result-title">
    <div className="section-heading"><div><span className="eyebrow">DECISION RECORD</span><h2 id="result-title">{retention[result.retention] || result.retention}</h2></div><span className="tag">快照 r{result.pin.profile_revision}</span></div>
    <p className="notice">{result.pin.context.game_id === "lootweave-fixture" ? "这是合成机制验证结果，尚不代表已验证的游戏建议或 DPS。" : "下方显示已确认物品的字段差异；真实游戏机制和 DPS 尚未验证。"}</p>
    {result.comparison.item_rolls && <div className="roll-delta"><h3>实际词条对比</h3><p className="muted">{result.comparison.item_rolls.current_item?.name || "当前槽位无物品记录"} → {result.comparison.item_rolls.candidate_item.name || "候选物品"}。仅比较物品字段；缺失值保留为未知，不作为零值。</p>
      {result.comparison.item_rolls.rows.length ? <table><thead><tr><th>词条</th><th>当前物品</th><th>候选物品</th><th>差值</th><th>核对状态</th></tr></thead><tbody>{result.comparison.item_rolls.rows.map(row => <tr key={row.affix_id}><td>{statNames[row.affix_id] || row.affix_id}</td><td>{rollValue(row.current_value, row.current_unit)}</td><td>{rollValue(row.candidate_value, row.candidate_unit)}</td><td>{row.delta === null ? "—" : (row.delta > 0 ? "+" : "") + row.delta + (row.current_unit === "percent" || row.current_unit === "percent_points" ? " 百分点" : " " + (units[row.current_unit || ""] || row.current_unit || ""))}</td><td>{rollStates[row.status] || row.status}</td></tr>)}</tbody></table> : <p className="muted">尚无实际词条，请在装备表单中录入。</p>}
      <p className="muted">差值不代表 DPS 或提升比例，特殊效果、套装与完整构筑需要另外核对。</p>
    </div>}
    {(result.future_preparation ?? []).length > 0 && <div className="future-preparation">
      <h3>未来配装的准备条件</h3>
      <p className="muted">按本次已核对的方案、角色等级、解锁条件、材料和预算计算。预计结果只属于计划，游戏中的实际结果需重新核对；条件满足也不代表 DPS 或真实游戏机制已验证。</p>
      {result.future_preparation!.map(plan => <details open key={plan.future_build_index}>
        <summary>未来构筑 {plan.future_build_index + 1} · {({ feasible: "满足已记录的准备条件", infeasible: "当前条件不满足", unknown: "准备条件待确认" })[plan.status]}</summary>
        <p>原可行性声明：{feasibility[plan.declared_feasibility] || plan.declared_feasibility}</p>
        <p>预计技能：{plan.skill_allocations.map(skill => skill.id + " · " + skill.rank + " 级 · " + (owners[skill.actor || "hero"] || skill.actor)).join("、") || "未记录"}</p>
        {plan.options.filter(option => option.kind === "equipment").map(option => {
          const item = option.projected_result;
          return item && "affixes" in item ? <p key={option.id}>预计改后物品：{item.name || option.target_id} · 强化 {item.upgrade_state.known ? item.upgrade_state.level : "未知"}
            {item.affixes.map(affix => " · " + (statNames[affix.id] || affix.id) + " " + rollValue(affix.value, affix.unit)).join("")}</p> : null;
        })}
        {plan.build_sources && <details><summary>完整未来配置（计划，不会写入当前档案）</summary>
          {sourceKinds.map(kind => { const group = sourceGroups[kind]; return <p key={kind}>{group.title}：{plan.build_sources![group.key].map(source =>
            source.id + (group.ranks ? " · " + source.rank + " 级" : "") + " · " + (owners[source.actor ?? group.actor] || source.actor)
            + (source.companion_id ? " · 归属 " + source.companion_id : "") + (source.level ? " · 仆从等级 " + source.level : "")
            + (source.set_id ? " · 符文组 " + source.set_id : "") + (source.effects.length ? " · 效果 " + source.effects.join("、") : "")).join("；") || "无选定来源"}</p>; })}
          {plan.equipped_items && <p>预计装备：{Object.entries(plan.equipped_items).map(([slot, item]) =>
            (slots[slot] || slot) + " · " + (item.name || item.instance_id)).join("；")}</p>}
          {plan.conditions && <p>预计条件：{Object.entries(plan.conditions).map(([id, state]) => id + " · " + (mechanismStates[state] || state)).join("；") || "无已记录条件"}</p>}
        </details>}
        {plan.comparison && <div className="future-comparison"><h4>完整未来配置的机制变化</h4>
          <p className="muted">实际当前配置 → 此计划的完整预计配置。准备费用满足与配置需求满足分别核对。</p>
          {plan.comparison.status === "blocked" && <p className="warning">计划配置的机制比较受阻，请先核对缺失依据。</p>}
          <MechanismChanges comparison={plan.comparison} future />
          {(plan.comparison.blockers ?? []).length > 0 && <ul>{plan.comparison.blockers!.map(code => <li key={code}>{blockerLabel(code)}</li>)}</ul>}
          <details><summary>未来机制来源与依据</summary><table><thead><tr><th>机制</th><th>归属</th><th>实际当前</th><th>计划未来</th><th>来源与依据</th></tr></thead>
            <tbody>{plan.comparison.after.map(row => <tr key={row.rule_id}><td>{label(row.capability || "")}</td><td>{owners[row.actor || ""] || "归属未知"}</td>
              <td>{mechanismStates[plan.comparison!.before.find(original => original.rule_id === row.rule_id)?.state || "unknown"]}</td><td>{mechanismStates[row.state || "unknown"]}</td>
              <td>{row.source_ids?.join("、") || "无"} · 输入：{row.input_evidence_ids.join("、")} · 规则：{row.evidence_ids.join("、")}</td></tr>)}</tbody></table></details>
        </div>}
        {plan.resources.length > 0 && <table><thead><tr><th>材料或货币</th><th>已确认费用合计</th><th>持有</th><th>预算上限</th><th>材料缺口</th><th>超出预算</th></tr></thead>
          <tbody>{plan.resources.map(row => <tr key={row.resource_id}><td>{row.resource_id}</td><td>{row.cost ?? "待确认"}</td><td>{row.available ?? "待核对"}</td><td>{row.budget_limit ?? "未设上限"}</td><td>{row.missing ?? "待核对"}</td><td>{row.budget_excess ?? "未设上限"}</td></tr>)}</tbody></table>}
        {plan.blockers.length > 0 && <ul>{plan.blockers.map(reason => <li key={reason}>{blockerLabel(reason)}</li>)}</ul>}
        <small>准备方案依据：{plan.input_evidence_ids.join("、") || "待核对"}</small>
      </details>)}
    </div>}
    <div className="verdict"><strong>{status[result.comparison.status] || result.comparison.status}</strong><span>保留价值与立即换装分别判断</span></div>
    <MechanismChanges comparison={result.comparison} />
    {result.comparison.equip_blockers.map(x => <p className="warning" key={x}>{x === "required_level_not_met" ? "尚未达到穿戴等级；仍可保留。" : "职业穿戴要求不满足。"}</p>)}
    {result.blockers.length > 0 && <details open><summary>缺失依据与待确认项（{result.blockers.length}）</summary><ul>{result.blockers.map(x => <li key={x}>{blockerLabel(x)}</li>)}</ul></details>}
    {result.reasons.length > 0 && <h3>用途说明与依据</h3>}
    {result.reasons.map((r, i) => <div className="reason" key={i}><strong>{r.capability ? mechanismLabel(r.capability, r.actor) : "当前用途"}</strong><p>{r.kind === "future_use" ? "在未来构筑 " + ((r.future_build_index ?? 0) + 1) + " 中存在用途；可行性声明：" + (feasibility[r.feasibility || ""] || r.feasibility || "未确认") : r.kind === "low_current_relevance" ? "未发现已知的当前或选定未来用途；其他用途仍可能存在。" : "在当前确认条件下，这件物品提供此机制。"} </p>{r.future_equipment && r.future_equipment.length > 0 && <p>所选配套：{r.future_equipment.map(item => (slots[item.slot] || item.slot) + " · " + (item.name || "未命名物品")).join("、")}</p>}<small>规则依据：{r.evidence_ids.join("、") || "无适用规则"} · 输入依据：{r.input_evidence_ids.join("、")}</small></div>)}
    <details><summary>完整配置与依据</summary><table><thead><tr><th>机制</th><th>归属</th><th>替换前</th><th>替换后</th><th>来源</th></tr></thead><tbody>{result.comparison.after.map(r => <tr key={r.rule_id}><td>{label(r.capability || "")}</td><td>{owners[r.actor || ""] || "归属未知"}</td><td>{result.comparison.before.find(x => x.rule_id === r.rule_id)?.state}</td><td>{r.state}</td><td>{r.source_ids?.join("、") || "无"}</td></tr>)}</tbody></table></details>
    <footer className="result-footer"><span>规则包 {result.pin.pack_version} · 评估器 {result.pin.evaluator_version} · 意图 r{result.pin.intent_revision}</span><button type="button" onClick={onReplay} disabled={replaying}>{replaying ? "回放中…" : replayed ? "✓ 回放一致 · 再次验证" : "回放验证"}</button></footer>
  </section>;
}
