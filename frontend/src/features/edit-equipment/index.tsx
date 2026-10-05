import { useState } from "react";
import { isExactCount, newId } from "../../shared/api";
import { SourceFields, SourceList } from "../../entities/build-source";
import type { Item, PreparationOption, Snapshot } from "../../shared/api";
import { canMapField, emptyItem, slots, statLabels, unitLabels } from "./model";
import type { ObservedItemField } from "./model";
export { emptySnapshot, mapItemField } from "./model";

const entries = (text: string) => [...new Set(text.split(/[,，\n]/).map(x => x.trim()).filter(Boolean))];
const numeric = (text: string) => text.trim() ? Number(text) : Number.NaN;

export function ItemEditor({ item, onChange, kind = "equipped" }: { item: Item; onChange: (item: Item) => void; kind?: "candidate" | "equipped" | "inventory" | "projected" }) {
  const candidate = kind === "candidate";
  const itemKind = kind === "projected" ? "预计改后物品" : kind === "candidate" ? "候选物品" : kind === "inventory" ? "库存物品" : "已装备物品";
  const update = (patch: Partial<Item>) => onChange({ ...item, ...patch });
  const changeAffix = (index: number, patch: Partial<Item["affixes"][number]>) => update({ affixes: item.affixes.map((row, i) => i === index ? { ...row, ...patch } : row) });
  return <div className="item-editor">
    <div className="fields"><label>物品名称<input aria-label={itemKind + "名称"} value={item.name || ""} onChange={e => update({ name: e.target.value })}/></label>
      {(candidate || kind === "inventory") && <label>{candidate ? "替换槽位" : "物品槽位"}<select aria-label={candidate ? "候选槽位" : "库存物品槽位"} value={item.slot} onChange={e => update({ slot: e.target.value })}>{Object.entries(slots).map(([id, name]) => <option key={id} value={id}>{name}</option>)}{!slots[item.slot] && <option value={item.slot}>{item.slot}</option>}</select></label>}
      <label>穿戴等级<input type="number" min="1" step="1" placeholder="未知时留空" value={item.required_level ?? ""} onChange={e => update({ required_level: e.target.value ? Number(e.target.value) : null })}/></label>
      <label>限定职业<input placeholder="不限职业时留空" value={item.class_id || ""} onChange={e => update({ class_id: e.target.value.trim() || undefined })}/></label></div>
    <h3>{kind === "projected" ? "已核对的预计词条" : "实际词条"}</h3><p className="muted">同一词条请选择相同标识和单位；这里记录实际值，数值增加不等于构筑更强。</p>
    <div className="affix-list editable-affixes">{item.affixes.map((row, i) => <div className="affix-row" key={i}>
      <label>词条<select aria-label="词条标识" value={statLabels[row.id] ? row.id : "custom"} onChange={e => changeAffix(i, { id: e.target.value === "custom" ? newId("stat") : e.target.value })}>{Object.entries(statLabels).map(([id, name]) => <option key={id} value={id}>{name}</option>)}<option value="custom">其他词条</option></select></label>
      {!statLabels[row.id] && <label>词条标识<input aria-label="自定义词条标识" value={row.id} onChange={e => changeAffix(i, { id: e.target.value })}/></label>}
      <label>实际数值<input aria-label="词条实际数值" type="number" step="any" value={Number.isFinite(row.value) ? row.value : ""} onChange={e => changeAffix(i, { value: numeric(e.target.value) })}/></label>
      <label>单位<select aria-label="词条单位" value={row.unit} onChange={e => changeAffix(i, { unit: e.target.value })}>{Object.entries(unitLabels).map(([id, name]) => <option key={id} value={id}>{name}</option>)}{!unitLabels[row.unit] && <option value={row.unit}>{row.unit || "待填写"}</option>}</select></label>
      <button type="button" aria-label={"删除词条 " + (statLabels[row.id] || row.id)} onClick={() => update({ affixes: item.affixes.filter((_, j) => j !== i) })}>删除</button>
    </div>)}</div>
    <button type="button" onClick={() => update({ affixes: [...item.affixes, { id: newId("stat"), value: Number.NaN, unit: "points", evidence_ids: [...item.evidence_ids] }] })}>添加词条</button>
    <details><summary>特殊效果、套装与未确认属性</summary>
      <label>效果标识（逐行或逗号分隔）<textarea rows={2} value={item.effects.join("\n")} onChange={e => update({ effects: entries(e.target.value) })}/></label>
      <label className="check"><input type="checkbox" checked={!item.unknowns.includes("effects_not_reviewed")} onChange={e => update({ unknowns: e.target.checked ? item.unknowns.filter(x => x !== "effects_not_reviewed") : [...new Set([...item.unknowns, "effects_not_reviewed"])] })}/>我已核对特殊效果和镶嵌来源；没有效果时列表留空。</label>
      <label>套装标识<input value={item.set_id || ""} onChange={e => update({ set_id: e.target.value.trim() || undefined })}/></label>
      <label>未揭示属性<textarea rows={2} value={item.unrevealed_properties.join("\n")} onChange={e => update({ unrevealed_properties: entries(e.target.value) })}/></label>
      <label>其他待确认项<textarea rows={2} value={item.unknowns.filter(x => x !== "effects_not_reviewed").join("\n")} onChange={e => update({ unknowns: [...item.unknowns.filter(x => x === "effects_not_reviewed"), ...entries(e.target.value)] })}/></label>
    </details>
    <div className="fields"><label>强化等级<input type="number" min="0" step="1" placeholder="未知时留空" value={item.upgrade_state.known ? item.upgrade_state.level ?? 0 : ""} onChange={e => update({ upgrade_state: e.target.value ? { known: true, level: Number(e.target.value) } : { known: false } })}/></label><label>插槽数量<input type="number" min="0" step="1" placeholder="未知时留空" value={item.socket_state.known ? item.socket_state.count ?? 0 : ""} onChange={e => update({ socket_state: e.target.value ? { known: true, count: Number(e.target.value) } : { known: false } })}/></label></div>
    <SourceList title="镶嵌物品" sources={item.embedded_items} evidenceIds={item.evidence_ids}
      onChange={embedded_items => update({ embedded_items, unknowns: [...new Set([...item.unknowns, "effects_not_reviewed"])] })}/>
    <p className="muted">按已确认的宝石或嵌入效果录入。更改镶嵌来源后，请重新核对特殊效果；未识别的内容仍须保留为待确认。</p>
  </div>;
}

export function EquipmentEditor({ facts, onChange }: { facts: Snapshot; onChange: (facts: Snapshot) => void }) {
  const [otherSlot, setOtherSlot] = useState("head");
  const [inventorySlot, setInventorySlot] = useState("head");
  const slot = facts.candidate_item.slot;
  const current = facts.equipped_items[slot];
  const mode = current ? "item" : facts.unknowns.includes("current_slot_not_reviewed") ? "unknown" : "empty";
  const setCurrent = (item: Item) => onChange({ ...facts, equipped_items: { ...facts.equipped_items, [item.slot]: item } });
  return <>
    <div className="workspace-grid"><section className="panel"><div className="section-heading"><div><span className="eyebrow">02 · CANDIDATE</span><h2>候选物品</h2></div><span className="tag">{slots[slot] || slot}</span></div>
      <ItemEditor kind="candidate" item={facts.candidate_item} onChange={item => { const unknowns = facts.unknowns.filter(x => x !== "current_slot_not_reviewed"); if (item.slot !== slot && !facts.equipped_items[item.slot]) unknowns.push("current_slot_not_reviewed"); else if (item.slot === slot && mode === "unknown") unknowns.push("current_slot_not_reviewed"); onChange({ ...facts, candidate_item: item, unknowns }); }}/></section>
      <section className="panel"><div className="section-heading"><div><span className="eyebrow">03 · CURRENT EQUIPMENT</span><h2>当前同槽装备</h2></div><span className="tag">{slots[slot] || slot}</span></div>
        <label>当前装备状态<select aria-label="当前装备状态" value={mode} onChange={e => { const equipped = { ...facts.equipped_items }; if (e.target.value === "item") equipped[slot] = current || emptyItem(facts.evidence_ids, slot); else delete equipped[slot]; const unknowns = facts.unknowns.filter(x => x !== "current_slot_not_reviewed"); if (e.target.value === "unknown") unknowns.push("current_slot_not_reviewed"); onChange({ ...facts, equipped_items: equipped, unknowns }); }}><option value="unknown">尚未核对</option><option value="item">已装备物品</option><option value="empty">已确认空槽</option></select></label>
        {current ? <ItemEditor item={current} onChange={setCurrent}/> : <p className="muted">{mode === "unknown" ? "请填写当前装备或明确确认空槽，不能把未填写当作空装备位。" : "已确认这个槽位没有装备；不会把缺失词条按零计算。"}</p>}
      </section></div>
    <details className="panel"><summary>其他装备位（{Object.keys(facts.equipped_items).filter(key => key !== slot).length}）</summary><p className="muted">保留整套已装备物品的效果和套装来源。</p>
      {Object.entries(facts.equipped_items).filter(([key]) => key !== slot).map(([key, item]) => <details key={key}><summary>{slots[key] || key} · {item.name || "未命名"}</summary><ItemEditor item={item} onChange={setCurrent}/><button type="button" onClick={() => { const equipped = { ...facts.equipped_items }; delete equipped[key]; onChange({ ...facts, equipped_items: equipped }); }}>移除此槽装备</button></details>)}
      <div className="fields"><label>新增装备位<select value={otherSlot} onChange={e => setOtherSlot(e.target.value)}>{Object.entries(slots).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><button type="button" disabled={!!facts.equipped_items[otherSlot] || otherSlot === slot} onClick={() => onChange({ ...facts, equipped_items: { ...facts.equipped_items, [otherSlot]: emptyItem(facts.evidence_ids, otherSlot) } })}>添加已装备物品</button></div>
    </details>
    <details className="panel"><summary>其他已持有物品（{facts.inventory_items?.length ?? "未记录"}）</summary>
      <p className="muted">仅记录背包或仓库中的其他装备，不会加入当前构筑。候选物品和已装备物品已分别记录；库存未核对不等于空库存。</p>
      {facts.inventory_items === undefined ? <div><p className="muted">此快照尚未记录库存。开始核对会建立一个部分核对的库存；只有之后明确选择完整核对，空库存才表示已确认没有其他持有物品。</p><button type="button" onClick={() => onChange({ ...facts, inventory_items: [], inventory_coverage: "partial" })}>开始核对库存</button></div> : <>
        {facts.inventory_items.map((item, index) => <details key={item.instance_id}><summary>{slots[item.slot] || item.slot} · {item.name || "未命名"}</summary><ItemEditor kind="inventory" item={item} onChange={updated => onChange({ ...facts, inventory_items: facts.inventory_items!.map((entry, i) => i === index ? updated : entry), inventory_coverage: "partial" })}/><button type="button" aria-label={"删除库存物品 " + (item.name || item.instance_id)} onClick={() => onChange({ ...facts, inventory_items: facts.inventory_items!.filter((_, i) => i !== index), inventory_coverage: "partial" })}>删除库存物品</button></details>)}
        <div className="fields"><label>新增库存槽位<select aria-label="新增库存物品槽位" value={inventorySlot} onChange={e => setInventorySlot(e.target.value)}>{Object.entries(slots).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><button type="button" onClick={() => onChange({ ...facts, inventory_items: [...facts.inventory_items!, emptyItem(facts.evidence_ids, inventorySlot)], inventory_coverage: "partial" })}>添加库存物品</button></div>
      </>}
    </details>
  </>;
}

export function ObservationFields({ fields, onApply, onReviewed }: { fields: ObservedItemField[]; onApply: (field: ObservedItemField) => void; onReviewed: () => void }) {
  return <div className="ocr-fields"><h3>核对识别字段</h3><p className="muted">确认字段含义后填入候选物品。通用等级可能是物品、角色或穿戴等级，只有确认是穿戴要求后才能填入；有歧义的内容请手动改正。</p>
    {fields.map((field, index) => <div className="observation-row" key={index}><span>{field.field === "level" ? "等级（含义待确认）" : statLabels[field.field] || field.field}：{field.value ?? "数值未知"} {unitLabels[field.unit || ""] || field.unit || "单位未知"}{field.ambiguous ? " · 存在歧义" : ""}</span><button type="button" disabled={!canMapField(field)} onClick={() => onApply(field)}>{field.field === "level" ? "确认是穿戴要求，填入穿戴等级" : "填入候选物品"}</button></div>)}
    <button type="button" onClick={onReviewed}>已逐项核对，未使用字段已手动处理或忽略</button>
  </div>;
}


export function PreparationOptionsEditor({ facts, onChange }: { facts: Snapshot; onChange: (facts: Snapshot) => void }) {
  const options = facts.preparation_options ?? [];
  const ownedItems = [facts.candidate_item, ...Object.values(facts.equipped_items), ...(facts.inventory_items ?? [])];
  const replace = (index: number, option: PreparationOption) => onChange({ ...facts,
    preparation_options: options.map((entry, i) => i === index ? option : entry) });
  const remove = (index: number) => onChange({ ...facts, preparation_options: options.filter((_, i) => i !== index) });
  const add = (kind: "equipment" | "skill") => {
    const common = { id: newId("preparation"), context: structuredClone(facts.context), class_id: facts.class_id,
      evidence_ids: [...facts.evidence_ids], unknowns: ["outcome_not_confirmed"], costs: null,
      requirements: { required_level: null, max_rank: null, unlock_state: "unknown" as const } };
    const item = facts.candidate_item;
    const skillId = newId("skill");
    const option: PreparationOption = kind === "equipment"
      ? { ...common, kind, target_id: item.instance_id, input: structuredClone(item),
          result: { ...structuredClone(item), record_kind: "projected_item" } }
      : { ...common, kind, target_id: skillId, input: null,
          result: { id: skillId, rank: 0, effects: [], actor: "hero", evidence_ids: [...facts.evidence_ids] } };
    onChange({ ...facts, preparation_options: [...options, option] });
  };
  const count = (raw: string) => isExactCount(raw) ? Number(raw) : Number.NaN;
  const shown = (amount: number) => Number.isSafeInteger(amount) && amount >= 0 ? amount : "";
  return <details className="panel">
    <summary>学习技能与装备改造方案（{options.length}）</summary>
    <p className="muted">按游戏中已核对的学习、升级或改造条件录入。这里只保存计划；随机结果和未知费用请保留待确认。实际执行后须重新核对物品或技能并保存新档案。</p>
    {options.map((option, index) => <details key={option.id}>
      <summary>{option.kind === "skill" ? "技能" : "装备改造"} · {option.target_id}</summary>
      <p className="muted">方案依据：{option.evidence_ids.join("、")} · 版本：{option.context.edition} / {option.context.game_build}</p>
      {option.kind === "equipment" ? <>
        <label>要改造的持有物品<select aria-label="改造目标物品" value={option.target_id}
          onChange={event => {
            const selected = ownedItems.find(item => item.instance_id === event.target.value);
            if (selected) replace(index, { ...option, target_id: selected.instance_id,
              input: structuredClone(selected), result: { ...structuredClone(selected), record_kind: "projected_item" },
              unknowns: [...new Set([...option.unknowns, "outcome_not_confirmed"])] });
          }}>
          {ownedItems.map(item => <option key={item.instance_id} value={item.instance_id}>{slots[item.slot] || item.slot} · {item.name || item.instance_id}</option>)}
          {!ownedItems.some(item => item.instance_id === option.target_id) && <option value={option.target_id}>已缺失 · {option.target_id}</option>}
        </select></label>
        <ItemEditor kind="projected" item={option.result} onChange={result => replace(index, { ...option, result,
          unknowns: [...new Set([...option.unknowns, "outcome_not_confirmed"])] })} />
      </> : <>
        <p className="muted">填写计划完成后的技能等级与效果；等级 0 表示撤销分配。原等级：{option.input?.rank ?? "当前未分配"}。</p>
        <SourceFields source={option.result} ranks setIds={false} defaultActor="hero" onDelete={() => remove(index)}
          onChange={result => replace(index, { ...option, result, target_id: result.id,
            input: result.id === option.target_id ? option.input : structuredClone(facts.skills.find(skill => skill.id === result.id) ?? null),
            unknowns: [...new Set([...option.unknowns, "outcome_not_confirmed"])] })} />
      </>}
      <div className="fields">
        <label>此操作要求的角色等级<input aria-label="方案要求等级" type="number" min="1" step="1" value={option.requirements.required_level ?? ""}
          onChange={event => replace(index, { ...option, requirements: { ...option.requirements,
            required_level: event.target.value === "" ? null : count(event.target.value) } })} /></label>
        {option.kind === "skill" && <label>已确认技能等级上限<input aria-label="方案技能等级上限" type="number" min="1" step="1" value={option.requirements.max_rank ?? ""}
          onChange={event => replace(index, { ...option, requirements: { ...option.requirements,
            max_rank: event.target.value === "" ? null : count(event.target.value) } })} /></label>}
        <label>学习或改造条件<select aria-label="方案解锁状态" value={option.requirements.unlock_state}
          onChange={event => replace(index, { ...option, requirements: { ...option.requirements,
            unlock_state: event.target.value as "unlocked" | "locked" | "unknown" } })}>
          <option value="unknown">尚未确认解锁</option><option value="unlocked">已确认可以操作</option><option value="locked">已确认尚未解锁</option>
        </select></label>
      </div>
      <label className="check"><input aria-label="已核对方案全部费用" type="checkbox" checked={option.costs !== null && !option.unknowns.includes("costs_not_confirmed")}
        onChange={event => replace(index, { ...option, costs: event.target.checked ? option.costs ?? [] : option.costs,
          unknowns: event.target.checked ? option.unknowns.filter(value => value !== "costs_not_confirmed")
            : [...new Set([...option.unknowns, "costs_not_confirmed"])] })} />我已核对全部费用；确实免费时费用列表留空。</label>
      {option.costs !== null && <>
        {option.costs.map((cost, costIndex) => <div className="fields" key={costIndex}>
          <label>消耗的材料或货币英文 ID<input aria-label="方案费用资源" value={cost.resource_id}
            onChange={event => replace(index, { ...option, costs: option.costs!.map((entry, i) => i === costIndex ? { ...entry, resource_id: event.target.value } : entry) })} /></label>
          <label>消耗个数<input aria-label="方案费用个数" type="number" min="0" step="1" value={shown(cost.amount)}
            onChange={event => replace(index, { ...option, costs: option.costs!.map((entry, i) => i === costIndex ? { ...entry, amount: count(event.target.value) } : entry) })} /></label>
          <button type="button" onClick={() => replace(index, { ...option, costs: option.costs!.filter((_, i) => i !== costIndex) })}>删除费用</button>
        </div>)}
        <button type="button" onClick={() => replace(index, { ...option, costs: [...option.costs!, { resource_id: "", amount: Number.NaN }] })}>添加方案费用</button>
      </>}
      <label className="check"><input aria-label="已核对方案预计结果" type="checkbox" checked={!option.unknowns.includes("outcome_not_confirmed")}
        onChange={event => replace(index, { ...option, unknowns: event.target.checked
          ? option.unknowns.filter(value => value !== "outcome_not_confirmed")
          : [...new Set([...option.unknowns, "outcome_not_confirmed"])] })} />我已核对以上预计结果；不存在未记录的随机结果。</label>
      <label>其他不确定项（每行一项）<textarea rows={2} value={option.unknowns.filter(value => value !== "outcome_not_confirmed").join("\n")}
        onChange={event => replace(index, { ...option, unknowns: [...option.unknowns.filter(value => value === "outcome_not_confirmed"),
          ...event.target.value.split("\n").map(value => value.trim()).filter(Boolean)] })} /></label>
      <button type="button" onClick={() => remove(index)}>删除准备方案</button>
    </details>)}
    <div className="fields"><button type="button" onClick={() => add("skill")}>添加技能准备方案</button>
      <button type="button" onClick={() => add("equipment")}>添加装备改造方案</button></div>
  </details>;
}
