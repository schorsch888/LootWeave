import { memo, useState } from "react";
import type { ExternalObservation } from "../../shared/api";
import { CombatReports, LineageReports, LoadoutReports, RunReports, StatusReports } from "./reports";

const views = ["角色状态", "战斗面板", "容量与材料", "跑图与统计", "掉落预览", "数据可用性", "实战伤害", "血脉记录", "配装资料", "采集状态"];
const labels: Record<string, string> = {
  dps: "面板 DPS", toughness: "坚韧", recovery: "恢复", max_hp: "最大生命", aps: "每秒攻击次数",
  dps_exact: "未取整 DPS", weapon_damage: "武器伤害", flat_damage: "附加伤害", value: "数值", mult: "倍率",
  chance: "暴击率原始值", damage: "暴击伤害原始值", elemental: "元素倍率", conditional: "条件倍率",
  ability_type: "技能类型倍率", total: "总倍率", inventory: "背包", storage: "仓库", carriage: "马车",
  waves_total: "总波数", wave_index: "波次索引（原始值）", enemies_remaining: "当前波剩余敌人",
  planned_items: "日志计划物品数", picked_unminted: "待结算数（来源推断）", collected: "日志收集数", granted: "日志发放数",
  runs: "日志跑图次数", committed: "日志已结算次数", planned: "日志计划总数",
  total_game_time_s: "累计游戏时间（秒）", total_earned_gold: "累计金币", total_earned_exp: "累计经验", total_deaths: "累计死亡次数",
  basic_attack: "普通攻击", strong_attack: "强力攻击", special_1: "特殊技能 1", special_2: "特殊技能 2",
  character: "角色", final_stats: "角色属性", panel: "战斗面板", equipment: "身上装备", talents: "天赋",
  carriage_capacity: "马车容量", fullness_alerts: "满载警报", ground_drops: "地面掉落", run_progress: "跑图进度",
  run_history: "日志跑图记录", statistics: "累计统计", runplan_forecast: "预生成掉落", chest_preview: "未开宝箱",
  town_plan: "回城清单", recommendations: "装备推荐", ground_upgrade_alerts: "地面升级推荐", gamble_queue: "赌博队列",
};
const states: Record<string, string> = { enabled: "已读取", partial: "部分读取", disabled: "已禁用", unavailable: "未读取",
  computing: "计算中", queued: "排队中", error: "读取失败", off_by_policy: "采集设置已关闭", never_exported: "数据源未提供", degraded: "读取异常", removed: "已移除" };
const stages: Record<string, string> = { collected: "已收集（预览标签）", ground: "地面", carriage: "马车", in_flight: "运输中", pending: "待结算", upcoming: "尚未出现", missed: "未收集" };
const show = (value: unknown): string => value === null || value === undefined || value === "" ? "未知" : String(value);
const yes = (value: boolean | null) => value === null ? "未知" : value ? "是" : "否";
const panelKeys = ["dps", "toughness", "recovery", "max_hp", "aps", "dps_exact", "weapon_damage", "flat_damage"] as const;
const runKeys = ["waves_total", "wave_index", "enemies_remaining", "planned_items", "picked_unminted", "collected", "granted"] as const;
const statisticsKeys = ["total_game_time_s", "total_earned_gold", "total_earned_exp", "total_deaths"] as const;

function Values({ values }: { values: [string, unknown][] }) {
  return <dl className="live-values">{values.map(([key, value]) => <div key={key}><dt>{labels[key] || key}</dt><dd>{show(value)}</dd></div>)}</dl>;
}

export const LiveOverview = memo(function LiveOverview({ data, character, reports, buildSources }: { data: ExternalObservation["overview"]; character: ExternalObservation["character"]; reports: ExternalObservation["telemetry"]; buildSources: ExternalObservation["build_sources"] }) {
  const [view, setView] = useState(0);
  const [waveIndex, setWaveIndex] = useState(0);
  const [chestIndex, setChestIndex] = useState(0);
  const [previewKind, setPreviewKind] = useState("ground");
  const [page, setPage] = useState(0);
  const char = data.character;
  const wave = data.forecast.waves[Math.min(waveIndex, Math.max(0, data.forecast.waves.length - 1))];
  const chest = data.chests[Math.min(chestIndex, Math.max(0, data.chests.length - 1))];
  const previews = previewKind === "forecast" ? wave?.items ?? [] : previewKind === "chests" ? chest?.contents ?? [] : data.ground;
  const pages = Math.max(1, Math.ceil(previews.length / 50));
  const currentPage = Math.min(page, pages - 1);
  return <div className="live-overview">
    <div className="draft-actions" role="group" aria-label="实时数据面板">{views.map((name, index) => <button type="button" key={name} aria-pressed={view === index} onClick={() => setView(index)}>{name}</button>)}</div>
    <section aria-label={views[view]}>
      {view === 0 && <>
        <h3>角色当前状态</h3>
        <Values values={[["金币", character.gold], ["当前经验", char.xp], ["生命", `${show(char.hp.current)} / ${show(char.hp.max)}`],
          ["法力", `${show(char.mana.current)} / ${show(char.mana.max)}`], ["场景", char.area], ["状态", char.game_state],
          ["地图", char.map.label || char.map.key], ["城镇", char.town.label || char.town.key], ["主属性", char.primary_stat],
          ["巅峰已解锁", yes(char.paragon.unlocked)], ["巅峰等级", char.paragon.level], ["巅峰经验", char.paragon.xp]]}/>
        <h3>技能与天赋</h3>
        <p className="muted">等级和说明来自数据源。效果机制仍需核对。</p>
        <ul>{data.abilities.map((ability, index) => <li key={index}>{labels[ability.role] || ability.role || "技能"}：{ability.name || "未知"} · 等级 {show(ability.rank)}</li>)}</ul>
        {data.talents.map((talent, index) => <details key={index}><summary>{talent.name || "未知天赋"} · {show(talent.rank)} / {show(talent.max)} · {talent.tree}</summary><p>{talent.description || "没有读取到说明。"}</p></details>)}
        {!data.abilities.length && !data.talents.length && <p>技能和天赋尚未读取。</p>}
        {Object.entries(buildSources).map(([name, entries]) => <details key={name}><summary>{{ paragon: "巅峰分配", runes: "符文", companions: "随从", temporary_effects: "临时效果" }[name as keyof typeof buildSources]} · {entries.length} 条观测</summary>{entries.length ? <ul>{entries.map(entry => <li key={entry.id}>{entry.name || entry.id} · 等级／点数 {show(entry.rank ?? entry.level)}</li>)}</ul> : <p>尚未采集。</p>}<p className="muted">观测标识和等级需要核对。效果机制仍未验证。</p></details>)}
        {data.potion_slots.length > 0 && <p>药剂栏：{data.potion_slots.map(value => value || "空槽").join("、")}</p>}
      </>}
      {view === 1 && <>
        <h3>数据源计算的战斗面板</h3>
        <p className="notice">这些值是数据源的面板估计，不能代表实战 DPS 或已验证的换装收益。</p>
        <Values values={panelKeys.map(key => [key, data.panel[key]])}/>
        <p>与游戏界面显示一致：{yes(data.panel.game_labels_match)}</p>
        {Object.values(data.panel.game_labels).some(Boolean) && <Values values={Object.entries(data.panel.game_labels).map(([key, value]) => ["游戏显示 " + (labels[key] || key), value])}/>}
        <details><summary>查看数据源计算组成</summary><Values values={Object.entries(data.panel.primary)}/><Values values={Object.entries(data.panel.crit)}/><Values values={Object.entries(data.panel.bonus)}/><p>{data.panel.formula || "没有读取到公式。"}</p></details>
        <details><summary>角色最终属性与基础属性</summary><p>以下为读取的原始数值，单位仍需核对。</p><h3>最终属性</h3><Values values={Object.entries(data.stats.final)}/><h3>基础属性</h3><Values values={Object.entries(data.stats.base)}/><p>数据源最终属性校验：{yes(data.stats.validation.final_stats_match)}</p></details>
      </>}
      {view === 2 && <>
        <h3>容量与满载状态</h3>
        <Values values={Object.entries(data.capacity).map(([key, value]) => [labels[key], `${show(value.used)} / ${show(value.capacity)} · ${value.level === "full" ? "已满" : value.level === "warn" ? "接近满载" : value.level === "ok" ? "有空位" : "状态未知"}${value.kind === "helper_estimate" ? "（数据源计算容量）" : ""}`])}/>
        <p>马车运输中：{show(data.in_flight_count)}。运输中的物品尚未计入持有装备。</p>
        <Values values={[["马车含运输的占用", data.capacity.carriage.fullness_used], ["当前随从", data.carriage.active_companion],
          ["随从基础容量", data.carriage.base_capacity], ["附加容量原始值", data.carriage.extra_capacity],
          ["容量与游戏显示一致", yes(data.carriage.game_label_match)], ["游戏容量显示", data.carriage.game_label],
          ["数据源读取的背包自动填充", yes(data.carriage.autofill_inventory)], ["数据源读取的战斗状态", yes(data.carriage.in_combat)],
          ["数据源读取的拾取筛选", data.carriage.pickup_rarities?.join("、")]]}/>
        {data.alerts.map((alert, index) => <p className="warning" key={index}>数据源提示：{alert.detail || alert.code}</p>)}
        <details><summary>仓库页面容量</summary><ul>{data.storage_pages.map((entry, index) => <li key={index}>页 {entry.page === null ? "未知" : entry.page + 1}：{show(entry.used)} / {show(entry.capacity)} · 可用：{yes(entry.usable)}</li>)}</ul></details>
        <h3>已读取材料</h3>
        <p className="muted">有有效标识和数量的材料会随草稿载入。数量未知时保留未知，资源覆盖保留为部分。</p>
        <Values values={data.materials.map(entry => [entry.name, entry.amount])}/>
        {!data.materials.length && <p>没有读取到材料数据。</p>}
        <details><summary>数据源回城清单（仅供查看）</summary><p>数据源建议回城：{yes(data.town_checklist.go_to_town)}。下列项目来自数据源的收纳规则，仍需用户核对。</p>{(["open", "store", "review", "keep", "stash_all"] as const).map(key => <div key={key}><h3>{{ open: "建议打开或使用", store: "建议存放", review: "需核对", keep: "保留", stash_all: "全部存放清单" }[key]} · {data.town_checklist[key].length} 条</h3><ul>{data.town_checklist[key].slice(0, 50).map((entry, index) => <li key={index}>{entry.name} · {entry.container === "inventory" ? "背包" : entry.container === "carriage" ? "马车" : "位置未知"}</li>)}</ul>{data.town_checklist[key].length > 50 && <p>显示前 50 条。</p>}</div>)}</details>
      </>}
      {view === 3 && <>
        <h3>当前跑图</h3>
        <Values values={[["地图", data.run.map], ["难度", data.run.difficulty], ["正在跑图", yes(data.run.in_run)],
          ...runKeys.map(key => [key, data.run[key]] as [string, unknown]), ["本轮已结算", yes(data.run.committed)]]}/>
        <p className="muted">计划数来自日志。待结算数是来源推断。历史汇总不能确定丢失数量或掉落概率。</p>
        <h3>日志跑图记录</h3><Values values={Object.entries(data.history.totals)}/>
        <ol>{data.history.recent.map((entry, index) => <li key={index}>计划 {show(entry.planned)} · 收集 {show(entry.collected)} · 发放 {show(entry.granted)} · 金币 {show(entry.gold)} · 已结算 {yes(entry.committed)}</li>)}</ol>
        <h3>累计统计</h3><Values values={statisticsKeys.map(key => [key, data.statistics[key]])}/>
        <Values values={Object.entries(data.statistics.loot_counts_by_rarity).map(([key, value]) => ["累计掉落 " + key, value])}/>
      </>}
      {view === 4 && <>
        <h3>掉落与未开宝箱预览</h3><p className="notice">地面物品、预生成掉落和未开宝箱内容仅供查看。它们不会进入持有清单或候选装备。</p>
        <label>预览类型<select aria-label="预览类型" value={previewKind} onChange={event => { setPreviewKind(event.target.value); setPage(0); }}><option value="ground">地面掉落</option><option value="forecast">预生成掉落</option><option value="chests">未开宝箱</option></select></label>
        {previewKind === "forecast" && <><p>预生成掉落：{states[data.features.runplan_forecast] || "未读取"} · {data.forecast.map || "地图未知"}</p><label>预览波次<select aria-label="预览波次" value={waveIndex} onChange={event => { setWaveIndex(Number(event.target.value)); setPage(0); }}>{data.forecast.waves.map((entry, index) => <option key={index} value={index}>波次 {show(entry.wave ?? entry.index)} · {entry.items.length} 条</option>)}</select></label><Values values={Object.entries(data.forecast.totals)}/>{wave && <><p>该波预生成金币：{show(wave.gold)}</p><ul>{wave.enemies.map((enemy, index) => <li key={index}>{enemy.name} × {show(enemy.count)}</li>)}</ul></>}</>}
        {previewKind === "chests" && <><p>未开宝箱：{states[data.features.chest_preview] || "未读取"}</p><label>预览宝箱<select aria-label="预览宝箱" value={chestIndex} onChange={event => { setChestIndex(Number(event.target.value)); setPage(0); }}>{data.chests.map((entry, index) => <option key={index} value={index}>{entry.name || "宝箱 " + (index + 1)}</option>)}</select></label></>}
        <p>共 {previews.length} 条预览{previews.length > 50 ? ` · 第 ${currentPage + 1} / ${pages} 页` : ""}。</p>
        {previews.length > 50 && <div className="draft-actions"><button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>预览上一页</button><button type="button" disabled={currentPage + 1 === pages} onClick={() => setPage(currentPage + 1)}>预览下一页</button></div>}
        <ul>{previews.slice(currentPage * 50, (currentPage + 1) * 50).map((entry, index) => <li key={index}>{entry.name || "未知物品"} · {entry.rarity}{"status" in entry && entry.status ? " · " + (stages[entry.status] || "状态待核对") : ""}{"modifiers" in entry && entry.modifiers.length > 0 && <details><summary>预览词条（未持有）</summary>{entry.modifiers.map((modifier, i) => <p key={i}>{modifier.stat}：{show(modifier.value)}（单位待核对）</p>)}</details>}</li>)}</ul>
        {!previews.length && <p>当前没有可用预览。请在数据可用性面板核对采集状态。</p>}
      </>}
      {view === 5 && <>
        <h3>本次数据可用性</h3><Values values={Object.entries(data.features).map(([key, value]) => [labels[key] || key, states[value] || "未读取"])}/>
        <p className="muted">未采集的功能保留未知。当前数据不能证明装备推荐。</p>
      </>}
      {view === 3 && <RunReports report={reports.runs}/>}
      {view === 6 && <CombatReports report={reports.combat}/>}
      {view === 7 && <LineageReports report={reports.lineage}/>}
      {view === 8 && <LoadoutReports report={reports.loadouts}/>}
      {view === 9 && <StatusReports report={reports.status}/>}
    </section>
  </div>;
});
