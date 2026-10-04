import { useState } from "react";
import { newId } from "../../shared/api";
import { SourceList } from "../../entities/build-source";
import type { Item, Snapshot } from "../../shared/api";
import { canMapField, emptyItem, slots, statLabels, unitLabels } from "./model";
import type { ObservedItemField } from "./model";
export { emptySnapshot, mapItemField } from "./model";

const entries = (text: string) => [...new Set(text.split(/[,，\n]/).map(x => x.trim()).filter(Boolean))];
const numeric = (text: string) => text.trim() ? Number(text) : Number.NaN;

export function ItemEditor({ item, onChange, candidate = false }: { item: Item; onChange: (item: Item) => void; candidate?: boolean }) {
  const update = (patch: Partial<Item>) => onChange({ ...item, ...patch });
  const changeAffix = (index: number, patch: Partial<Item["affixes"][number]>) => update({ affixes: item.affixes.map((row, i) => i === index ? { ...row, ...patch } : row) });
  return <div className="item-editor">
    <div className="fields"><label>物品名称<input aria-label={candidate ? "候选物品名称" : "已装备物品名称"} value={item.name || ""} onChange={e => update({ name: e.target.value })}/></label>
      {candidate && <label>替换槽位<select aria-label="候选槽位" value={item.slot} onChange={e => update({ slot: e.target.value })}>{Object.entries(slots).map(([id, name]) => <option key={id} value={id}>{name}</option>)}{!slots[item.slot] && <option value={item.slot}>{item.slot}</option>}</select></label>}
      <label>穿戴等级<input type="number" min="1" step="1" placeholder="未知时留空" value={item.required_level ?? ""} onChange={e => update({ required_level: e.target.value ? Number(e.target.value) : null })}/></label>
      <label>限定职业<input placeholder="不限职业时留空" value={item.class_id || ""} onChange={e => update({ class_id: e.target.value.trim() || undefined })}/></label></div>
    <h3>实际词条</h3><p className="muted">同一词条请选择相同标识和单位；这里记录实际值，数值增加不等于构筑更强。</p>
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
  const slot = facts.candidate_item.slot;
  const current = facts.equipped_items[slot];
  const mode = current ? "item" : facts.unknowns.includes("current_slot_not_reviewed") ? "unknown" : "empty";
  const setCurrent = (item: Item) => onChange({ ...facts, equipped_items: { ...facts.equipped_items, [item.slot]: item } });
  return <>
    <div className="workspace-grid"><section className="panel"><div className="section-heading"><div><span className="eyebrow">02 · CANDIDATE</span><h2>候选物品</h2></div><span className="tag">{slots[slot] || slot}</span></div>
      <ItemEditor candidate item={facts.candidate_item} onChange={item => { const unknowns = facts.unknowns.filter(x => x !== "current_slot_not_reviewed"); if (item.slot !== slot && !facts.equipped_items[item.slot]) unknowns.push("current_slot_not_reviewed"); else if (item.slot === slot && mode === "unknown") unknowns.push("current_slot_not_reviewed"); onChange({ ...facts, candidate_item: item, unknowns }); }}/></section>
      <section className="panel"><div className="section-heading"><div><span className="eyebrow">03 · CURRENT EQUIPMENT</span><h2>当前同槽装备</h2></div><span className="tag">{slots[slot] || slot}</span></div>
        <label>当前装备状态<select aria-label="当前装备状态" value={mode} onChange={e => { const equipped = { ...facts.equipped_items }; if (e.target.value === "item") equipped[slot] = current || emptyItem(facts.evidence_ids, slot); else delete equipped[slot]; const unknowns = facts.unknowns.filter(x => x !== "current_slot_not_reviewed"); if (e.target.value === "unknown") unknowns.push("current_slot_not_reviewed"); onChange({ ...facts, equipped_items: equipped, unknowns }); }}><option value="unknown">尚未核对</option><option value="item">已装备物品</option><option value="empty">已确认空槽</option></select></label>
        {current ? <ItemEditor item={current} onChange={setCurrent}/> : <p className="muted">{mode === "unknown" ? "请填写当前装备或明确确认空槽，不能把未填写当作空装备位。" : "已确认这个槽位没有装备；不会把缺失词条按零计算。"}</p>}
      </section></div>
    <details className="panel"><summary>其他装备位（{Object.keys(facts.equipped_items).filter(key => key !== slot).length}）</summary><p className="muted">保留整套已装备物品的效果和套装来源。</p>
      {Object.entries(facts.equipped_items).filter(([key]) => key !== slot).map(([key, item]) => <details key={key}><summary>{slots[key] || key} · {item.name || "未命名"}</summary><ItemEditor item={item} onChange={setCurrent}/><button type="button" onClick={() => { const equipped = { ...facts.equipped_items }; delete equipped[key]; onChange({ ...facts, equipped_items: equipped }); }}>移除此槽装备</button></details>)}
      <div className="fields"><label>新增装备位<select value={otherSlot} onChange={e => setOtherSlot(e.target.value)}>{Object.entries(slots).map(([id, name]) => <option key={id} value={id}>{name}</option>)}</select></label><button type="button" disabled={!!facts.equipped_items[otherSlot] || otherSlot === slot} onClick={() => onChange({ ...facts, equipped_items: { ...facts.equipped_items, [otherSlot]: emptyItem(facts.evidence_ids, otherSlot) } })}>添加已装备物品</button></div>
    </details>
  </>;
}

export function ObservationFields({ fields, onApply, onReviewed }: { fields: ObservedItemField[]; onApply: (field: ObservedItemField) => void; onReviewed: () => void }) {
  return <div className="ocr-fields"><h3>核对识别字段</h3><p className="muted">确认字段含义后填入候选物品。通用等级可能是物品、角色或穿戴等级，只有确认是穿戴要求后才能填入；有歧义的内容请手动改正。</p>
    {fields.map((field, index) => <div className="observation-row" key={index}><span>{field.field === "level" ? "等级（含义待确认）" : statLabels[field.field] || field.field}：{field.value ?? "数值未知"} {unitLabels[field.unit || ""] || field.unit || "单位未知"}{field.ambiguous ? " · 存在歧义" : ""}</span><button type="button" disabled={!canMapField(field)} onClick={() => onApply(field)}>{field.field === "level" ? "确认是穿戴要求，填入穿戴等级" : "填入候选物品"}</button></div>)}
    <button type="button" onClick={onReviewed}>已逐项核对，未使用字段已手动处理或忽略</button>
  </div>;
}
