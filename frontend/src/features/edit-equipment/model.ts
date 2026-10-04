import { newId } from "../../shared/api";
import type { GameContext, Item, Snapshot } from "../../shared/api";

export type ObservedItemField = { field: string; value: number | null; unit: string | null; ambiguous: boolean };
export const statLabels: Record<string, string> = { vitality: "活力", armor: "护甲", strength: "力量", dexterity: "敏捷", intelligence: "智力", max_health: "最大生命", max_mana: "最大法力", attack_speed: "攻击速度", critical_chance: "暴击率", critical_damage: "暴击伤害", fire_damage: "火焰伤害", cold_damage: "冰冷伤害", lightning_damage: "闪电伤害", physical_damage: "物理伤害", "fixture-vitality": "示例活力", "fixture-cold-bonus": "示例冰冷加成" };
export const unitLabels: Record<string, string> = { points: "点", percent: "%", percent_points: "百分点", per_second: "每秒", seconds: "秒" };
export const slots: Record<string, string> = { weapon: "武器", offhand: "副手", head: "头部", body: "胸部", hands: "手部", waist: "腰部", legs: "腿部", feet: "脚部", neck: "项链", ring1: "戒指 1", ring2: "戒指 2", shoulders: "护肩", back: "披风" };

export function emptyItem(evidenceIds: string[], slot = "weapon"): Item {
  return { record_kind: "item_instance", instance_id: newId("item"), name: "", slot, required_level: null, effects: [], affixes: [], unrevealed_properties: [], embedded_items: [], unknowns: ["effects_not_reviewed"], upgrade_state: { known: false }, socket_state: { known: false }, evidence_ids: [...evidenceIds] };
}

export function emptySnapshot(context?: GameContext): Snapshot {
  const capturedAt = new Date().toISOString();
  const evidenceId = newId("manual");
  return { context: context || { game_id: "deskrawl", edition: "unknown", game_build: "unknown", mode: "online", season: "not_applicable", ruleset_id: "unknown", content_entitlements: [] }, class_id: "sorcerer", character_level: 1, captured_at: capturedAt, evidence: [{ id: evidenceId, kind: "manual_confirmation", source_ref: "manual://typed-input", captured_at: capturedAt, verification: "confirmed", conflicts: [] }], evidence_ids: [evidenceId], skills: [], talents: [], paragon: [], account_unlocks: {}, runes: [], companions: [], temporary_effects: [], observed_panel: [], conditions: {}, inventory_coverage: "unknown", unknowns: ["build_not_reviewed", "current_slot_not_reviewed"], equipped_items: {}, candidate_item: emptyItem([evidenceId]) };
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
