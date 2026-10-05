import type { Intent, Snapshot } from "../../shared/api";
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
      conditions: { ...facts.conditions }, feasibility: "", equipment_items: [] },
  ] }));

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
      <SourceList title="技能" sources={facts.skills} evidenceIds={facts.evidence_ids} ranks onChange={skills => updateFacts({ skills })} />
      <SourceList title="天赋" sources={facts.talents} evidenceIds={facts.evidence_ids} ranks onChange={talents => updateFacts({ talents })} />
      <SourceList title="巅峰" sources={facts.paragon} evidenceIds={facts.evidence_ids} ranks onChange={paragon => updateFacts({ paragon })} />
      <SourceList title="符文" sources={facts.runes} evidenceIds={facts.evidence_ids} setIds onChange={runes => updateFacts({ runes })} />
      <SourceList title="仆从" sources={facts.companions} evidenceIds={facts.evidence_ids} defaultActor="companion" onChange={companions => updateFacts({ companions })} />
      <SourceList title="临时效果" sources={facts.temporary_effects} evidenceIds={facts.evidence_ids} onChange={temporary_effects => updateFacts({ temporary_effects })} />
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
          <label><input type="checkbox" checked={intent.allowed_build_changes.includes("skills")}
            onChange={event => updateIntent(current => ({ ...current, allowed_build_changes: event.target.checked
              ? [...new Set([...current.allowed_build_changes, "skills"])]
              : current.allowed_build_changes.filter(value => value !== "skills") }))} /> 技能</label>
          <label><input type="checkbox" aria-label="允许更改装备" checked={intent.allowed_build_changes.includes("equipment")}
            onChange={event => updateIntent(current => ({ ...current, allowed_build_changes: event.target.checked
              ? [...new Set([...current.allowed_build_changes, "equipment"])]
              : current.allowed_build_changes.filter(value => value !== "equipment") }))} /> 装备</label>
        </fieldset>
        {intent.future_builds.map((build, index) => <div className="source-list" key={index}>
          <strong>未来构筑 {index + 1}</strong>
          <label>技能标识（逗号分隔）<input value={build.skills.join(", ")}
            onChange={event => updateIntent(current => ({ ...current, future_builds: current.future_builds.map((item, i) => i === index
              ? { ...item, skills: listValue(event.target.value) } : item) }))} /></label>
          <label>可行性<select value={build.feasibility} onChange={event => updateIntent(current => ({ ...current,
            future_builds: current.future_builds.map((item, i) => i === index ? { ...item, feasibility: event.target.value } : item),
          }))}>
            <option value="">请选择 · 未确认</option><option value="owned">已拥有</option><option value="obtainable">可获取</option><option value="hypothetical">假设构筑</option>
          </select></label>
          <p className="muted">可行性是你的声明；技能解锁、材料和预算仍需核实。</p>
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
