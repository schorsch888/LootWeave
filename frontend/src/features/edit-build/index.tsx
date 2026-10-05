import { isExactCount } from "../../shared/api";
import { sourceGroups, sourceKinds } from "../../shared/build-sources";
import type { Intent, ResourceCost, Snapshot } from "../../shared/api";
import { SourceList } from "../../entities/build-source";
import { slots } from "../../shared/equipment-labels";

function listValue(value: string): string[] {
  return value.split(",").map(part => part.trim()).filter(Boolean);
}

const unknownLabels: Record<string, string> = {
  build_not_reviewed: "构筑未核对（build_not_reviewed）",
  current_slot_not_reviewed: "当前槽位未核对（current_slot_not_reviewed）",
};

function unknownText(values: string) {
  return values.split("\n").map(value => unknownLabels[value] ?? value).join("\n");
}

function parseUnknownText(value: string) {
  const reverse = Object.fromEntries(Object.entries(unknownLabels).map(([key, label]) => [label, key]));
  return value.split("\n").map(line => reverse[line.trim()] ?? line.trim()).filter(Boolean);
}

export function BuildEditor({ facts, intent, onFactsChange, onIntentChange }: {
  facts: Snapshot;
  intent: Intent;
  onFactsChange: (facts: Snapshot) => void;
  onIntentChange: (intent: Intent) => void;
}) {
  const updateFacts = (patch: Partial<Snapshot>) => onFactsChange({ ...facts, ...patch });
  const updateIntent = (edit: (current: Intent) => Intent) => {
    const next = edit(intent);
    const { revision: _nextRevision, ...nextContent } = next;
    const { revision: _currentRevision, ...currentContent } = intent;
    if (JSON.stringify(nextContent) !== JSON.stringify(currentContent)) {
      onIntentChange({ ...next, revision: intent.revision + 1 });
    }
  };
  const markBuildReviewed = (reviewed: boolean) => {
    const unknowns = facts.unknowns.filter(value => value !== "build_not_reviewed");
    if (!reviewed) unknowns.push("build_not_reviewed");
    updateFacts({ unknowns });
  };
  const addFuture = () => updateIntent(current => ({ ...current, future_builds: [
    ...current.future_builds,
    { skills: facts.skills.filter(skill => skill.rank && skill.rank > 0).map(skill => skill.id),
      conditions: { ...facts.conditions }, feasibility: "", equipment_items: [],
      ...Object.fromEntries(sourceKinds.filter(kind => kind !== "skill").map(kind => {
        const group = sourceGroups[kind];
        return [group.key, facts[group.key].filter(source => !group.ranks || (source.rank ?? 0) > 0).map(source => source.id)];
      })) },
  ] }));

  const limits = Array.isArray(intent.budget.resource_limits) ? intent.budget.resource_limits as ResourceCost[] : [];
  const ownedItems = [...(facts.inventory_items ?? []), ...Object.values(facts.equipped_items)]
    .filter(item => item.slot !== facts.candidate_item.slot);

  return <div className="build-editor">
    <div className="section-heading"><div><span className="eyebrow">BUILD FACTS &amp; GOALS</span><h2>构筑事实与目标需求</h2></div></div>
    <p className="muted">这里只记录已确认的事实和需求标识。未填写的构筑信息请保留在未知项中；本表单不会推断规则、权重或 DPS，也不会默认构筑完整。</p>
    <label>装备库存覆盖<select value={facts.inventory_items === undefined ? "unknown" : facts.inventory_coverage}
      onChange={event => updateFacts({ inventory_coverage: event.target.value })}>
      <option value="complete" disabled={facts.inventory_items === undefined}>完整核对</option><option value="partial">部分核对</option><option value="unknown">尚不清楚</option>
    </select></label>
    {facts.inventory_items === undefined && <p className="muted">请先在“其他已持有物品”中开始核对库存；旧档案缺少记录不能当作已确认空库存。</p>}
    <label className="check"><input type="checkbox" checked={!facts.unknowns.includes("build_not_reviewed")}
      onChange={event => markBuildReviewed(event.target.checked)} /> 我已核对当前技能、天赋、巅峰、符文、仆从和临时状态</label>
    <details>
      <summary>未知或待确认事项（{facts.unknowns.length}）</summary>
      <p className="muted">每行一项。build_not_reviewed 表示构筑未核对；current_slot_not_reviewed 表示当前装备槽位未核对。</p>
      <label>未知或待确认事项<textarea rows={3} value={unknownText(facts.unknowns.join("\n"))}
        onChange={event => updateFacts({ unknowns: parseUnknownText(event.target.value) })} /></label>
    </details>

    <div className="build-source">
      {sourceKinds.map(kind => {
        const group = sourceGroups[kind];
        return <SourceList key={kind} title={group.title} sources={facts[group.key]} evidenceIds={facts.evidence_ids}
          ranks={group.ranks} setIds={group.setIds} defaultActor={group.actor} levels={kind === "companion"}
          onChange={sources => updateFacts({ [group.key]: sources })} />;
      })}
    </div>

    <details>
      <summary>目标需求与未来构筑</summary>
      <div className="fields">
        <label>所需能力标识（每行一项）<textarea rows={3} value={intent.required_capabilities.join("\n")}
          onChange={event => {
            const required_capabilities = event.target.value.split("\n").map(line => line.trim()).filter(Boolean);
            updateIntent(current => ({ ...current, required_capabilities }));
          }} /></label>
        <fieldset className="check">
          <legend>允许改变的构筑部分</legend>
          {sourceKinds.map(kind => {
            const group = sourceGroups[kind];
            return <label key={kind}><input type="checkbox" aria-label={kind === "skill" ? undefined : "允许更改" + group.title}
              checked={intent.allowed_build_changes.includes(group.key)}
              onChange={event => updateIntent(current => ({ ...current, allowed_build_changes: event.target.checked
                ? [...new Set([...current.allowed_build_changes, group.key])]
                : current.allowed_build_changes.filter(value => value !== group.key) }))} /> {group.title}</label>;
          })}
          <label><input type="checkbox" aria-label="允许更改装备" checked={intent.allowed_build_changes.includes("equipment")}
            onChange={event => updateIntent(current => ({ ...current, allowed_build_changes: event.target.checked
              ? [...new Set([...current.allowed_build_changes, "equipment"])]
              : current.allowed_build_changes.filter(value => value !== "equipment") }))} /> 装备</label>
        </fieldset>
        <fieldset>
          <legend>本次准备的材料与货币预算</legend>
          <p className="muted">不设置某项上限表示仅按已持有数量核对；填 0 表示不允许花费该项资源。各方案的费用会合并计算。</p>
          {limits.map((limit, limitIndex) => <div className="fields" key={limitIndex}>
            <label>预算资源英文 ID<input aria-label="预算资源" value={limit.resource_id}
              onChange={event => updateIntent(current => ({ ...current, budget: { ...current.budget,
                resource_limits: limits.map((entry, i) => i === limitIndex ? { ...entry, resource_id: event.target.value } : entry) } }))} /></label>
            <label>允许花费个数<input aria-label="预算上限" type="number" min="0" step="1" value={Number.isSafeInteger(limit.amount) && limit.amount >= 0 ? limit.amount : ""}
              onChange={event => updateIntent(current => ({ ...current, budget: { ...current.budget,
                resource_limits: limits.map((entry, i) => i === limitIndex ? { ...entry,
                  amount: isExactCount(event.target.value) ? Number(event.target.value) : Number.NaN } : entry) } }))} /></label>
            <button type="button" onClick={() => updateIntent(current => ({ ...current, budget: { ...current.budget,
              resource_limits: limits.filter((_, i) => i !== limitIndex) } }))}>删除预算上限</button>
          </div>)}
          <button type="button" onClick={() => updateIntent(current => ({ ...current, budget: { ...current.budget,
            resource_limits: [...limits, { resource_id: "", amount: Number.NaN }] } }))}>添加资源预算上限</button>
        </fieldset>
        {intent.future_builds.map((build, index) => <div className="source-list" key={index}>
          <strong>未来构筑 {index + 1}</strong>
          {sourceKinds.map(kind => {
            const group = sourceGroups[kind];
            const selected = build[group.key] ?? facts[group.key].filter(source => !group.ranks || (source.rank ?? 0) > 0).map(source => source.id);
            return <label key={kind}>{group.title}标识（逗号分隔）<input aria-label={"未来" + group.title + "标识"}
              value={selected.join(", ")} onChange={event => updateIntent(current => ({ ...current,
                future_builds: current.future_builds.map((item, i) => i === index ? { ...item, [group.key]: listValue(event.target.value) } : item) }))} /></label>;
          })}
          <p className="muted">未单独填写的部分沿用当前已确认来源；清空表示计划移除全部该类来源。新增、移除和调整都需要选择对应准备方案。</p>
          <label>可行性<select value={build.feasibility} onChange={event => updateIntent(current => ({ ...current,
            future_builds: current.future_builds.map((item, i) => i === index ? { ...item, feasibility: event.target.value } : item),
          }))}>
            <option value="">请选择 · 未确认</option><option value="owned">已拥有</option><option value="obtainable">可获取</option><option value="hypothetical">假设构筑</option>
          </select></label>
          <p className="muted">可行性声明会与已核对的等级、解锁、改造费用、材料数量和预算分别核对。新技能不会默认成 1 级。</p>
          <p className="muted">所选技能等级：{build.skills.map(skillId => {
            const planned = (facts.preparation_options ?? []).find(option => option.kind === "skill" && option.target_id === skillId
              && (build.preparation_options ?? []).includes(option.id));
            const source = planned?.kind === "skill" ? planned.result : facts.skills.find(skill => skill.id === skillId && (skill.rank ?? 0) > 0);
            return skillId + " · " + (source?.rank === undefined ? "等级待记录" : source.rank + " 级") + " · " + (source?.actor === "companion" ? "仆从" : "角色");
          }).join("、") || "暂无"}</p>
          <fieldset>
            <legend>选择构筑与装备准备方案</legend>
            {!(facts.preparation_options ?? []).length && <p className="muted">需要改变配置或改造装备时，请先在上方记录准备方案、条件和费用。</p>}
            {(facts.preparation_options ?? []).map(option => <label className="check" key={option.id}>
              <input type="checkbox" data-preparation-id={option.id} aria-label={"未来构筑 " + (index + 1) + " 准备方案 " + option.id}
                disabled={!intent.allowed_build_changes.includes(option.kind === "equipment" ? "equipment" : sourceGroups[option.kind].key)}
                checked={(build.preparation_options ?? []).includes(option.id)}
                onChange={event => updateIntent(current => ({ ...current, future_builds: current.future_builds.map((entry, i) => {
                  if (i !== index) return entry;
                  const refs = event.target.checked ? [...new Set([...(entry.preparation_options ?? []), option.id])]
                    : (entry.preparation_options ?? []).filter(ref => ref !== option.id);
                  if (option.kind === "equipment") return { ...entry, preparation_options: refs };
                  const group = sourceGroups[option.kind];
                  const selected = entry[group.key] ?? facts[group.key].filter(source => !group.ranks || (source.rank ?? 0) > 0).map(source => source.id);
                  const remaining = (facts.preparation_options ?? []).find(quote => quote.kind === option.kind
                    && quote.target_id === option.target_id && refs.includes(quote.id));
                  const projected = remaining && remaining.kind !== "equipment" ? remaining.result
                    : facts[group.key].find(source => source.id === option.target_id);
                  const include = projected != null && (!group.ranks || (projected.rank ?? 0) > 0);
                  return { ...entry, [group.key]: include ? [...new Set([...selected, option.target_id])]
                    : selected.filter(id => id !== option.target_id), preparation_options: refs };
                }) }))} />{option.kind === "equipment" ? "装备改造 · " + (option.result.name || option.target_id)
                  : sourceGroups[option.kind].title + " " + option.target_id + " → " + (option.result === null ? "移除"
                    : sourceGroups[option.kind].ranks ? option.result.rank + " 级" : "已记录的预计状态")} · {option.costs === null || option.unknowns.includes("costs_not_confirmed") ? "费用待核对"
                    : option.costs.length ? option.costs.map(cost => cost.resource_id + " × " + cost.amount).join("、") : "已核对免费"}
            </label>)}
            {(build.preparation_options ?? []).filter(ref => !(facts.preparation_options ?? []).some(option => option.id === ref)).map(ref =>
              <p className="warning" key={ref}>准备方案已缺失：{ref} <button type="button"
                onClick={() => updateIntent(current => ({ ...current, future_builds: current.future_builds.map((entry, i) => i === index
                  ? { ...entry, preparation_options: (entry.preparation_options ?? []).filter(id => id !== ref) } : entry) }))}>移除失效准备方案</button></p>)}
          </fieldset>
          <fieldset disabled={!intent.allowed_build_changes.includes("equipment")}>
            <legend>未来配套装备</legend>
            <p className="muted">从已录入的持有物品中选择。同一槽位只能选一件；未选择的槽位沿用换装后的当前装备，候选物品保持不变。</p>
            {!ownedItems.length && <p className="muted">暂无其他持有装备，请先在上方录入库存。</p>}
            {ownedItems.map(item => <label className="check" key={item.instance_id}>
              <input type="checkbox" data-item-id={item.instance_id}
                aria-label={"未来构筑 " + (index + 1) + " 配套 " + (slots[item.slot] || item.slot) + " " + (item.name || "未命名物品")}
                checked={(build.equipment_items ?? []).includes(item.instance_id)}
                onChange={event => updateIntent(current => ({ ...current,
                  future_builds: current.future_builds.map((entry, i) => i !== index ? entry : { ...entry,
                    equipment_items: event.target.checked
                      ? [...(entry.equipment_items ?? []).filter(ref => ref !== item.instance_id
                        && ownedItems.find(option => option.instance_id === ref)?.slot !== item.slot), item.instance_id]
                      : (entry.equipment_items ?? []).filter(ref => ref !== item.instance_id),
                  }),
                }))} /> {slots[item.slot] || item.slot} · {item.name || "未命名物品"}
            </label>)}
          </fieldset>
          {(build.equipment_items ?? []).filter(ref => !ownedItems.some(item => item.instance_id === ref)).map(ref =>
            <p className="warning" key={ref}>配套物品已缺失或不适用于此槽位：{ref} <button type="button"
              onClick={() => updateIntent(current => ({ ...current,
                future_builds: current.future_builds.map((entry, i) => i !== index ? entry : { ...entry,
                  equipment_items: (entry.equipment_items ?? []).filter(id => id !== ref),
                }),
              }))}>移除失效配套物品</button></p>)}
          <small className="muted">初始条件沿用当前已记录条件：{Object.keys(build.conditions).join("、") || "暂无"}</small>
          {Object.entries(build.conditions).map(([condition, state]) => <label key={condition}>{condition}<select value={state}
            onChange={event => updateIntent(current => ({ ...current, future_builds: current.future_builds.map((item, i) => i === index
              ? { ...item, conditions: { ...item.conditions, [condition]: event.target.value } } : item) }))}>
            <option value="active">已确认生效</option><option value="inactive">已确认未生效</option><option value="unknown">未知</option>
          </select></label>)}
          <button type="button" onClick={() => updateIntent(current => ({ ...current,
            future_builds: current.future_builds.filter((_, i) => i !== index),
          }))}>删除未来构筑</button>
        </div>)}
        <button type="button" onClick={addFuture}>添加未来构筑</button>
      </div>
    </details>
  </div>;
}
