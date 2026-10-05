type Numbers = Record<string, number | null>;
export type LocalReport<T> = { state: string; data: T | null };
export type LiveDamage = {
  dmg: number | null; hits: number | null; crits: number | null; kills: number | null; active: number | null;
  partial: boolean | null; sources: { id: string; name: string; actor: string; dmg: number | null; hits: number | null; crits: number | null; kills: number | null }[];
};
export type LiveFinding = {
  name: string; template_id: string; rarity: string; kind: string; slot: string; map: string; difficulty: string;
  boss: string; status: string; ancient: boolean | null; black_mist: boolean | null; market: boolean | null;
  item_level: number | null; price: number | null; wave: number | null; time: number | null; source: string; how: string; piece: string;
};
export type LiveRun = {
  id: string; map: string; difficulty: string; level: number | null; result: string; partial: boolean | null;
  t0: number | null; t1: number | null; dur: number | null; wave: number | null; waves: number | null;
  boss: number | null; exp: number | null; gold: number | null; deaths: number | null;
  loot: Numbers; damage: LiveDamage; special: Numbers; finds: LiveFinding[];
};
export type LiveRuns = {
  records: LiveRun[]; live: LiveRun | null; total: number | null; rates: Numbers;
  per_map: { map: string; difficulty: string; runs: number | null }[];
  window_maps: { map: string; difficulty: string; runs: number; dur: number; exp: number; gold: number; exp_s: number | null; gold_s: number | null }[];
};
export type LiveCombat = { coverage_started_at: number | null; live: Numbers; session: LiveDamage & { since: number | null; dur: number | null } };
export type LiveFrequency = { n: number; k: number; rate: number | null };
export type LiveGamble = {
  draws: number; shards: number | null; rarities: { rarity: string; count: number; frequency: number }[];
  top: LiveFrequency; ancient: LiveFrequency; black_mist: LiveFrequency; pieces: Record<string, Numbers>;
};
export type LiveLineage = {
  gamble: Record<"all" | "auto" | "manual", LiveGamble>; draws: LiveFinding[]; finds: LiveFinding[]; market: LiveFinding[];
};
export type LiveLoadouts = {
  slots: { slot: number; name: string; empty: boolean | null; worn: boolean | null;
    abilities: { role: string; key: string; name: string }[]; gear: { slot: string; key: string; name: string; rarity: string }[];
    missing: { slot: string; name: string; reason: string }[] }[]; in_use: number | null;
};
export type LiveStatus = {
  producer_version: string; events: { kind: string; action: string; ok: boolean | null; map: string }[];
  catalogs: {
    maps: { key: string; name: string; type: string; prerequisite: string; entry: { item: string; amount: number | null; difficulties: string[] }[] }[];
    potions: { key: string; name: string; description: string; recipe: { quantity: number | null; ingredients: { key: string; name: string; amount: number | null }[] } }[];
    affix_pools: Record<string, string[]>; gem_kinds: string[]; rune_rarities: string[];
  }; collection_coverage: Record<string, string>;
};
export type ExternalTelemetry = {
  contract: string; kind: "local_measurements"; status: LocalReport<LiveStatus>; runs: LocalReport<LiveRuns>;
  combat: LocalReport<LiveCombat>; lineage: LocalReport<LiveLineage>; loadouts: LocalReport<LiveLoadouts>;
};
