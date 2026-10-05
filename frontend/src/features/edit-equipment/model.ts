import { newId } from "../../shared/api";
import type { GameContext, Item, Snapshot } from "../../shared/api";

export type ObservedItemField = { field: string; value: number | null; unit: string | null; ambiguous: boolean; raw_text?: string };
export const statLabels: Record<string, string> = { vitality: "活力", armor: "护甲", strength: "力量", dexterity: "敏捷", intelligence: "智力", max_health: "最大生命", max_mana: "最大法力", attack_speed: "攻击速度", critical_chance: "暴击率", critical_damage: "暴击伤害", fire_damage: "火焰伤害", cold_damage: "冰冷伤害", lightning_damage: "闪电伤害", physical_damage: "物理伤害", "fixture-vitality": "示例活力", "fixture-cold-bonus": "示例冰冷加成" };
export const unitLabels: Record<string, string> = { points: "点", percent: "%", percent_points: "百分点", per_second: "每秒", seconds: "秒" };
export { slots } from "../../shared/equipment-labels";

export function emptyItem(evidenceIds: string[], slot = "weapon"): Item {
  return { record_kind: "item_instance", instance_id: newId("item"), name: "", slot, required_level: null, effects: [], affixes: [], unrevealed_properties: [], embedded_items: [], unknowns: ["effects_not_reviewed"], upgrade_state: { known: false }, socket_state: { known: false }, evidence_ids: [...evidenceIds] };
}

export function emptySnapshot(context?: GameContext): Snapshot {
  const capturedAt = new Date().toISOString();
  const evidenceId = newId("manual");
  return { context: context || { game_id: "deskrawl", edition: "unknown", game_build: "unknown", mode: "online", season: "not_applicable", ruleset_id: "unknown", content_entitlements: [] }, class_id: "sorcerer", character_level: 1, captured_at: capturedAt, evidence: [{ id: evidenceId, kind: "manual_confirmation", source_ref: "manual://typed-input", captured_at: capturedAt, verification: "confirmed", conflicts: [] }], evidence_ids: [evidenceId], skills: [], talents: [], paragon: [], account_unlocks: {}, runes: [], companions: [], temporary_effects: [], observed_panel: [], conditions: {}, inventory_coverage: "unknown", unknowns: ["build_not_reviewed", "current_slot_not_reviewed"], equipped_items: {}, inventory_items: [], candidate_item: emptyItem([evidenceId]) };
}

export function canMapField(field: ObservedItemField): boolean {
  return !field.ambiguous && field.value !== null && Number.isFinite(field.value) && (field.field === "level" ? Number.isInteger(field.value) && field.value >= 1 : ["vitality", "armor"].includes(field.field) && !!field.unit);
}

export function mapItemField(item: Item, field: ObservedItemField, evidenceId: string, confirmedRequiredLevel = false): Item {
  if (field.field === "level" && !confirmedRequiredLevel) throw new Error("请先确认该等级确实是穿戴要求。");
  if (!canMapField(field)) throw new Error("请先在装备表单中核对歧义、数值和单位。");
  const next = structuredClone(item);
  next.evidence_ids = [...new Set([...next.evidence_ids, evidenceId])];
  if (field.field === "level") next.required_level = field.value;
  else {
    const affix = { id: field.field, value: field.value!, unit: field.unit!, evidence_ids: [evidenceId] };
    const index = next.affixes.findIndex(row => row.id === field.field);
    if (index < 0) next.affixes.push(affix); else next.affixes[index] = affix;
  }
  return next;
}

export type ReviewedItemField = { kind: "affix"; id: string; value: number; unit: string } | { kind: "required_level"; value: number };
export type ObservationRow = { key: string; rawText: string; proposal?: ObservedItemField };

export function observationRows(rawText: string, fields: ObservedItemField[]): ObservationRow[] {
  // Only merge a proposal with a complete matching line. Partial or missing source
  // metadata stays visible separately, so an unparsed part cannot disappear.
  const remaining = new Set(fields.map((_, index) => index));
  const rows: ObservationRow[] = rawText.split(/\r\n|\r|\n/).flatMap((line, index) => {
    if (!line.trim()) return [];
    const match = [...remaining].find(i => fields[i].raw_text?.trim() === line.trim());
    if (match !== undefined) remaining.delete(match);
    return [{ key: "line-" + index, rawText: line, proposal: match === undefined ? undefined : fields[match] }];
  });
  for (const index of remaining) {
    const proposal = fields[index];
    rows.push({ key: "field-" + index, rawText: proposal.raw_text ?? proposal.field, proposal });
  }
  return rows.length ? rows : [{ key: "empty", rawText: "" }];
}

export function validReviewedItemField(field: ReviewedItemField): boolean {
  return field.kind === "required_level"
    ? Number.isSafeInteger(field.value) && field.value >= 1
    : /^[a-zA-Z0-9_.-]{1,100}$/.test(field.id) && Number.isFinite(field.value)
      && field.unit.trim().length > 0 && field.unit.length <= 40;
}

export function reviewTarget(field: ReviewedItemField): string {
  return field.kind === "required_level" ? "required_level" : "affix:" + field.id;
}

export function mapReviewedItemFields(item: Item, fields: ReviewedItemField[], evidenceId: string): Item {
  if (!fields.every(validReviewedItemField)) throw new Error("请核对每一行的字段标识、实际数值和单位。");
  if (new Set(fields.map(reviewTarget)).size !== fields.length) throw new Error("同一字段有多行，请合并或忽略重复行后再应用。");
  const next = structuredClone(item);
  if (fields.length) next.evidence_ids = [...new Set([...next.evidence_ids, evidenceId])];
  for (const field of fields) {
    if (field.kind === "required_level") next.required_level = field.value;
    else {
      const affix = { id: field.id, value: field.value, unit: field.unit, evidence_ids: [evidenceId] };
      const index = next.affixes.findIndex(row => row.id === field.id);
      if (index < 0) next.affixes.push(affix); else next.affixes[index] = affix;
    }
  }
  return next;
}
