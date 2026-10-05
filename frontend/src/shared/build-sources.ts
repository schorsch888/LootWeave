export const sourceGroups = {
  skill: { key: "skills", title: "技能", ranks: true, setIds: false, actor: "hero" },
  talent: { key: "talents", title: "天赋", ranks: true, setIds: false, actor: "hero" },
  paragon: { key: "paragon", title: "巅峰", ranks: true, setIds: false, actor: "hero" },
  rune: { key: "runes", title: "符文", ranks: false, setIds: true, actor: "hero" },
  companion: { key: "companions", title: "仆从", ranks: false, setIds: false, actor: "companion" },
  temporary_effect: { key: "temporary_effects", title: "临时效果", ranks: false, setIds: false, actor: "hero" },
} as const;
export type SourceKind = keyof typeof sourceGroups;
export type SourceGroup = (typeof sourceGroups)[SourceKind]["key"];
export const sourceKinds = Object.keys(sourceGroups) as SourceKind[];
