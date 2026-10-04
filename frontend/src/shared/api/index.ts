export type Evidence = { id: string; kind: string; source_ref: string; captured_at: string; verification: string; conflicts: string[] };
export type Source = { id: string; effects: string[]; evidence_ids: string[]; rank?: number; set_id?: string; actor?: string };
export type Item = { record_kind: string; instance_id: string; name?: string; slot: string; required_level: number | null; effects: string[]; affixes: { id: string; value: number; unit: string; evidence_ids: string[] }[]; unrevealed_properties: string[]; embedded_items: Source[]; unknowns: string[]; upgrade_state: { known: boolean; level?: number }; socket_state: { known: boolean; count?: number }; evidence_ids: string[]; set_id?: string };
export type GameContext = { game_id: string; edition: string; game_build: string; mode: string; season: string; ruleset_id: string; content_entitlements: string[] };
export type Snapshot = { context: GameContext; class_id: string; character_level: number; captured_at: string; evidence: Evidence[]; evidence_ids: string[]; skills: Source[]; talents: Source[]; paragon: Source[]; account_unlocks: Record<string, unknown>; runes: Source[]; companions: Source[]; temporary_effects: Source[]; observed_panel: { stat: string; value: number; unit: string; source_ids: string[]; evidence_ids: string[] }[]; conditions: Record<string, string>; inventory_coverage: string; unknowns: string[]; equipped_items: Record<string, Item>; candidate_item: Item };
export type Intent = { revision: number; scenario: string; required_capabilities: string[]; allowed_build_changes: string[]; future_builds: { skills: string[]; conditions: Record<string, string>; feasibility: string }[]; budget: Record<string, unknown> };
export type Pack = { pack_id: string; version: string; pack_hash: string; context: GameContext; class_id: string; scenario: string; execution_policy: string };
export type Reason = { kind?: string; rule_id?: string; capability?: string; explanation: string; evidence_ids: string[]; input_evidence_ids: string[]; source_ids?: string[]; state?: string; actor?: string; feasibility?: string };
export type Mechanism = { actor: "hero" | "companion"; capability: string };
export type MechanismState = "active" | "inactive" | "unknown";
export type UncertainMechanism = Mechanism & { before: MechanismState; after: MechanismState };
export type EvaluationResult = { evaluation_id: string; retention: string; comparison: { status: string; scope_compatible?: boolean; lost_capabilities: string[]; gained_capabilities: string[]; missing_requirements: string[]; lost_mechanisms?: Mechanism[]; gained_mechanisms?: Mechanism[]; missing_mechanisms?: Mechanism[]; uncertain_mechanisms?: UncertainMechanism[]; equip_blockers: string[]; before: Reason[]; after: Reason[] }; blockers: string[]; reasons: Reason[]; scope_notice: string; limitations: string[]; pin: { profile_revision: number; pack_version: string; pack_hash: string; evaluator_version: string; intent_revision: number; context: GameContext } };
export type Demo = { label: string; facts: Snapshot; intent: Intent };

const hash = new URLSearchParams(window.location.hash.slice(1));
let token = hash.get("session") || "";
if (token) {
  sessionStorage.setItem("lootweave-session", token);
  history.replaceState(null, "", window.location.pathname);
} else {
  token = sessionStorage.getItem("lootweave-session") || "";
}

const messages: Record<string, string> = {
  trial_measurement_out_of_range: "累计经验或完整耗时超出可靠计算范围，请核对实际试验记录。",
  invalid_sample_counts: "请填写有效的精确整数次数，成功次数不能超过尝试次数。",
  sample_version_required: "样本版本尚未确认，请先核对游戏版本与规则范围。",
  unauthorized: "会话已失效，请从桌面入口重新打开。",
  revision_conflict: "档案已更新，请重新读取后确认。",
  service_unavailable: "服务暂时不可用，已保存的快照仍会保留。",
  pack_hash_conflict: "规则包已变化，请重新选择明确的版本。",
  player_confirmation_required: "请核对原文并明确确认。",
  observation_time_conflict: "关联依据的采集时间与原始截图不一致，请按显示的截图时间核对完整构筑，保留其他时点的来源。",
  profile_observation_time_conflict: "该快照的原始采集时间存在冲突或无法核验，请重新核对后保存新修订；历史结果仍可回放。",
  invalid_capture_time: "原始采集时间无效，请重新采集或使用原文确认。",
  actual_roll_and_unit_required: "词条需要实际数值和单位。",
  replay_mismatch: "回放与历史结果不同，已阻止接受该结果。",
};

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const response = await fetch("/api/" + path, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + token },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const result = await response.json() as T & { error?: string };
    if (!response.ok) throw new Error(messages[result.error || ""] || "输入未被接受：" + (result.error || response.status));
    return result;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("请求超时，请稍后重试。");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export const newId = (prefix: string) => prefix + "-" + crypto.randomUUID();

export const sessionCredential = () => token;

export const isExactCount = (value: string) => /^\d+$/.test(value.trim()) && Number.isSafeInteger(Number(value));
