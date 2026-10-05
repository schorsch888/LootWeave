import type { SourceGroup, SourceKind } from "../build-sources";

export type Evidence = { id: string; kind: string; source_ref: string; captured_at: string; verification: string; conflicts: string[] };
export type Source = { id: string; effects: string[]; evidence_ids: string[]; rank?: number; set_id?: string; actor?: string; level?: number; companion_id?: string };
export type Item = { record_kind: string; instance_id: string; name?: string; class_id?: string; slot: string; required_level: number | null; effects: string[]; affixes: { id: string; name?: string; value: number; unit: string; evidence_ids: string[] }[]; unrevealed_properties: string[]; embedded_items: Source[]; unknowns: string[]; upgrade_state: { known: boolean; level?: number }; socket_state: { known: boolean; count?: number }; evidence_ids: string[]; set_id?: string };
export type ResourceCost = { resource_id: string; amount: number };
export type OwnedResources = { coverage: "complete" | "partial" | "unknown"; balances: (ResourceCost & { evidence_ids: string[] })[] };
export type PreparationRequirements = { required_level: number | null; max_rank: number | null; unlock_state: "unlocked" | "locked" | "unknown"; companion_id?: string };
export type PreparationOption = { id: string; context: GameContext; class_id: string; target_id: string; evidence_ids: string[]; unknowns: string[]; costs: ResourceCost[] | null; requirements: PreparationRequirements } & ({ kind: "equipment"; input: Item; result: Item } | { kind: SourceKind; input: Source | null; result: Source | null });
export type FuturePreparation = { future_build_index: number; status: "feasible" | "infeasible" | "unknown"; declared_feasibility: string; blockers: string[]; input_evidence_ids: string[]; options: { id: string; kind: string; target_id: string; projected_result: Item | Source | null }[]; skill_allocations: Source[]; build_sources?: Record<SourceGroup, Source[]>; comparison?: EvaluationComparison; equipped_items?: Record<string, Item>; conditions?: Record<string, string>; projection_kind?: "future_plan"; resources: { resource_id: string; cost: number | null; available: number | null; budget_limit: number | null; missing: number | null; budget_excess: number | null }[] };
export type GameContext = { game_id: string; edition: string; game_build: string; mode: string; season: string; ruleset_id: string; content_entitlements: string[] };
export type Snapshot = { context: GameContext; class_id: string; character_level: number; captured_at: string; evidence: Evidence[]; evidence_ids: string[]; skills: Source[]; talents: Source[]; paragon: Source[]; account_unlocks: Record<string, unknown>; runes: Source[]; companions: Source[]; temporary_effects: Source[]; observed_panel: { stat: string; value: number; unit: string; source_ids: string[]; evidence_ids: string[] }[]; conditions: Record<string, string>; inventory_coverage: string; unknowns: string[]; equipped_items: Record<string, Item>; inventory_items?: Item[]; owned_resources?: OwnedResources; preparation_options?: PreparationOption[]; candidate_item: Item };
export type FutureBuild = { skills: string[]; conditions: Record<string, string>; feasibility: string; equipment_items?: string[]; preparation_options?: string[] } & Partial<Record<SourceGroup, string[]>>;
export type Intent = { revision: number; scenario: string; required_capabilities: string[]; allowed_build_changes: string[]; future_builds: FutureBuild[]; budget: Record<string, unknown> };
export type Pack = { pack_id: string; version: string; pack_hash: string; context: GameContext; class_id: string; scenario: string; execution_policy: string; dependency_templates?: { template_id: string; label: string }[] };
export type ItemTemplateDependency = { template_id: string; template_name: string; ability_id: string; ability_name: string; template_object_id: string; effect_object_id: string; ability_object_id: string; object_links: { source_id: string; relation: "equipment_effect" | "affected_ability"; target_id: string }[]; status: "reviewed_static_only"; evidence_ids: string[]; unknowns: string[] };
export type ItemDependencyResult = { contract_version: 1; record_kind: "item_template_dependency"; scope: "reviewed_static_only"; mechanics_accepted: false; pack_id: string; pack_version: string; pack_hash: string; context: GameContext; class_id: string; dependency: ItemTemplateDependency; evidence: { id: string; source_ref: string; source_build: string; method: string; scope: string; results: string; unknowns: string; verification: string; conflicts: string[] }[] };
export type Reason = { kind?: string; rule_id?: string; capability?: string; explanation: string; evidence_ids: string[]; input_evidence_ids: string[]; source_ids?: string[]; state?: string; actor?: string; feasibility?: string; future_build_index?: number; future_equipment?: Pick<Item, "instance_id" | "slot" | "name">[]; preparation_status?: string; future_comparison?: EvaluationComparison };
export type Mechanism = { actor: "hero" | "companion"; capability: string };
export type MechanismState = "active" | "inactive" | "unknown";
export type UncertainMechanism = Mechanism & { before: MechanismState; after: MechanismState };
export type ItemRollComparison = { scope: string; current_item: { instance_id: string; name?: string } | null; candidate_item: { instance_id: string; name?: string }; rows: { affix_id: string; current_value: number | null; candidate_value: number | null; current_unit: string | null; candidate_unit: string | null; delta: number | null; status: string; input_evidence_ids: string[] }[]; limitations: string[] };
export type EvaluationComparison = { status: string; scope_compatible?: boolean; blockers?: string[]; item_rolls?: ItemRollComparison; lost_capabilities: string[]; gained_capabilities: string[]; missing_requirements: string[]; lost_mechanisms?: Mechanism[]; gained_mechanisms?: Mechanism[]; missing_mechanisms?: Mechanism[]; uncertain_mechanisms?: UncertainMechanism[]; equip_blockers: string[]; before: Reason[]; after: Reason[] };
export type EvaluationResult = { evaluation_id: string; retention: string; comparison: EvaluationComparison; blockers: string[]; reasons: Reason[]; future_preparation?: FuturePreparation[]; scope_notice: string; limitations: string[]; pin: { profile_revision: number; pack_version: string; pack_hash: string; evaluator_version: string; intent_revision: number; context: GameContext } };
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
  resource_amount_required: "材料、货币、费用和预算个数需要填写非负安全整数；未知时请继续核对。",
  resource_coverage_required: "请明确材料与货币的核对范围。",
  duplicate_resource_balance: "同一项材料或货币重复录入，请合并为当前实际持有数量。",
  duplicate_resource_cost: "同一准备方案重复记录了资源费用，请合并后核对。",
  duplicate_resource_budget: "同一项资源重复设置预算，请保留一个明确上限。",
  unsupported_budget_fields: "预算需要使用材料或货币资源上限，当前预算格式尚不支持。",
  resource_budget_required: "请填写资源预算上限列表。",
  preparation_options_required: "准备方案需要是明确的记录列表。",
  duplicate_preparation_option: "准备方案标识重复，请核对。",
  preparation_costs_required: "请核对方案全部费用；费用未知时保留未确认。",
  preparation_unlock_required: "请明确学习或改造条件是否已解锁。",
  preparation_requirements_required: "等级要求和等级上限需要正整数，未知时留空。",
  preparation_source_required: "准备方案需要明确的来源标识、预计结果和撤销状态。",
  preparation_source_owner_conflict: "准备方案不能将原来源转移给另一作用者或仆从。",
  source_level_required: "仆从实际等级需要正的安全整数；未知时留空。",
  source_companion_identity_conflict: "仆从归属需要与该仆从自己的标识一致，请核对。",
  unsupported_preparation_kind: "此评估版本不支持这类准备方案，请使用当前版本创建新评估。",
  unsupported_future_build_fields: "历史评估版本不支持扩展后的未来配置，请使用当前版本创建新评估。",
  future_sources_required: "未来配置需要明确的来源标识列表。",
  duplicate_future_source: "同一未来配置中的来源标识重复，请核对。",
  preparation_skill_required: "技能准备方案需要明确标识和非负目标等级。",
  preparation_item_identity_conflict: "改造方案的物品、槽位和职业必须与原物品一致。",
  preparation_skill_owner_conflict: "技能准备方案不能改变原技能的作用者。",
  projected_item_required: "方案预计物品需要明确标记为预计结果。",
  projected_socket_capacity_exceeded: "预计镶嵌物品数量超过已确认插槽个数，请核对。",
  projected_item_state_required: "预计强化等级和插槽个数需要非负整数；未知时留空。",
  duplicate_future_preparation: "未来组合重复选择了同一准备方案。",
  duplicate_future_skill: "未来构筑的技能标识重复，请核对。",
  inventory_items_required: "库存必须是物品列表；尚未核对时请保留未知覆盖状态。",
  duplicate_item_instance: "同一件物品重复录入，请核对候选、已装备和库存记录。",
  future_equipment_required: "请选择已记录的配套装备。",
  duplicate_future_equipment: "未来组合中同一件物品重复，请核对。",
  trial_measurement_out_of_range: "累计经验或完整耗时超出可靠计算范围，请核对实际试验记录。",
  invalid_sample_counts: "请填写有效的精确整数次数，成功次数不能超过尝试次数。",
  sample_version_required: "样本版本尚未确认，请先核对游戏版本与规则范围。",
  unauthorized: "会话已失效，请从桌面入口重新打开。",
  revision_conflict: "档案已更新，请重新读取后确认。",
  service_unavailable: "服务暂时不可用，已保存的快照仍会保留。",
  service_start_failed: "服务启动失败，请重试当前操作。",
  service_start_timeout: "服务启动超时，请重试当前操作。",
  service_not_ready: "服务尚未就绪，请稍后重试。",
  service_start_required: "服务尚未启动，请在服务状态中重试所需服务，再重试当前操作。",
  runtime_stopping: "本地服务正在关闭，请重新打开桌面入口。",
  pack_hash_conflict: "规则包已变化，请重新选择明确的版本。",
  pack_version_not_found: "所选资料版本不存在，请重新读取知识包。",
  dependency_scope_mismatch: "当前游戏版本、模式、职业或内容范围与资料不一致，请先核对。",
  dependency_data_unavailable: "此知识包尚未提供装备依赖资料，请保留未知。",
  dependency_template_not_found: "所选装备模板没有对应资料，请重新选择。",
  player_confirmation_required: "请核对原文并明确确认。",
  observation_time_conflict: "关联依据的采集时间与原始截图不一致，请按显示的截图时间核对完整构筑，保留其他时点的来源。",
  profile_observation_time_conflict: "该快照的原始采集时间存在冲突或无法核验，请重新核对后保存新修订；历史结果仍可回放。",
  invalid_capture_time: "原始采集时间无效，请重新采集或使用原文确认。",
  actual_roll_and_unit_required: "词条需要实际数值和单位。",
  invalid_identifier: "请填写英文、数字或下划线组成的稳定字段标识。",
  invalid_required_level: "请填写正整数穿戴等级，尚不清楚时留空。",
  character_level_required: "请填写角色的实际等级。",
  duplicate_affix_id: "同一物品的词条标识重复，请核对。",
  source_rank_required: "已分配的技能、天赋和巅峰需要明确的非负整数等级。",
  context_fields_required: "请填写完整游戏范围，未确认的版本请保留 unknown。",
  replay_mismatch: "回放与历史结果不同，已阻止接受该结果。",
};

export type RuntimeService = "profile" | "knowledge" | "evaluation" | "planning" | "ocr";
export type RuntimeStatus = {
  services: Record<string, { state: "dormant" | "starting" | "ready" | "failed" | "stopping" | "unavailable"; generation?: number }>;
  core_ready: boolean;
  startup_policy: "on-demand" | "eager";
  degraded: boolean;
};

type RequestOptions = { signal?: AbortSignal };
const starts = new Map<RuntimeService, Promise<void>>();
const serviceLabels: Record<RuntimeService, string> = { profile: "档案", knowledge: "知识包", evaluation: "评估", planning: "试验与样本", ocr: "文字识别" };

async function request<T>(path: string, body: unknown, deadline: number, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController();
  const cancel = () => controller.abort();
  options.signal?.throwIfAborted();
  options.signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(cancel, deadline);
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
    if (options.signal?.aborted) throw options.signal.reason;
    if (error instanceof DOMException && error.name === "AbortError") throw new Error("请求超时，请稍后重试。");
    throw error;
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", cancel);
  }
}

// Requests using live dependencies check the current owner generation. Only
// startup is shared; dispatched writes are never automatically retried.
export function ensureService(service: RuntimeService): Promise<void> {
  const existing = starts.get(service);
  if (existing) return existing;
  const start = request<{ service: string; state: string; generation: number }>("runtime/ensure", { service }, 10000)
    .then(result => {
      if (result.service !== service || result.state !== "ready" || !Number.isSafeInteger(result.generation) || result.generation < 0) {
        throw new Error("服务启动结果无法核验。");
      }
    })
    .catch(error => { throw new Error(serviceLabels[service] + "服务未就绪：" + (error instanceof Error ? error.message : "启动失败。") + "请重试当前操作；已填写内容会保留。"); })
    .finally(() => { if (starts.get(service) === start) starts.delete(service); });
  starts.set(service, start);
  return start;
}

function waitForService(start: Promise<void>, signal?: AbortSignal): Promise<void> {
  if (!signal) return start;
  signal.throwIfAborted();
  return new Promise((resolve, reject) => {
    const cancel = () => reject(signal.reason);
    signal.addEventListener("abort", cancel, { once: true });
    start.then(resolve, reject).finally(() => signal.removeEventListener("abort", cancel));
  });
}

export async function api<T>(path: string, body?: unknown, options: RequestOptions = {}): Promise<T> {
  options.signal?.throwIfAborted();
  const capability = path.split("/")[0] as RuntimeService;
  // Frozen reads/replays use the already-running evaluator's stored bytes. They
  // must not start or repair live Profile/Knowledge dependencies implicitly.
  const frozenHistory = body === undefined
    ? /^evaluation\/evaluations(?:\/(?!\.{1,2}$)[a-zA-Z0-9_.-]{1,100})?$/.test(path)
    : /^evaluation\/evaluations\/(?!\.{1,2}\/)[a-zA-Z0-9_.-]{1,100}\/replay$/.test(path);
  if (Object.hasOwn(serviceLabels, capability) && !frozenHistory) await waitForService(ensureService(capability), options.signal);
  options.signal?.throwIfAborted();
  return request<T>(path, body, 15000, options);
}

export const newId = (prefix: string) => prefix + "-" + crypto.randomUUID();

export const sessionCredential = () => token;

export const isExactCount = (value: string) => /^\d+$/.test(value.trim()) && Number.isSafeInteger(Number(value));
