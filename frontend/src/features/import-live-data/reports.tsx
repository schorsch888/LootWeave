import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { LiveCombat, LiveFinding, LiveLineage, LiveLoadouts, LiveRun, LiveRuns, LiveStatus, LocalReport } from "../../shared/api";

const labels: Record<string, string> = { dmg: "累计伤害计数", hits: "命中次数", crits: "暴击次数", kills: "击杀次数", active: "有伤害的秒数",
  dps10: "最近 10 秒 DPS", dps60: "最近 60 秒 DPS", active60: "最近 60 秒活跃秒数", dur: "时长（秒）", runs: "完整记录数",
  exp_s: "经验／秒", gold_s: "金币／秒", exp: "经验", gold: "金币", draws: "抽取次数", shards: "消耗碎片", top: "传奇与神圣",
  ancient: "远古", black_mist: "黑雾", basic_attack: "普通攻击", strong_attack: "强力攻击", special_1: "特殊技能 1", special_2: "特殊技能 2" };
const resultLabels: Record<string, string> = { clear: "完成", died: "死亡", skip: "跳过", left: "离开", live: "进行中", unknown: "未知" };
const show = (value: unknown) => value === null || value === undefined || value === "" ? "未知" : typeof value === "number" ? Number(value.toFixed(3)).toLocaleString() : String(value);
const time = (seconds: number | null) => seconds === null ? "未知" : new Date(seconds * 1000).toLocaleString();

function Values({ values }: { values: [string, unknown][] }) {
  return <dl className="live-values">{values.map(([name, value]) => <div key={name}><dt>{labels[name] || name}</dt><dd>{show(value)}</dd></div>)}</dl>;
}
function Report<T>({ report, children }: { report: LocalReport<T>; children: (data: T) => ReactNode }) {
  return <><p className="muted">{report.state === "enabled" ? "本次已接收此类观测。" : report.state === "partial" ? "此类观测只有部分覆盖。" : "未采集：当前数据源没有提供此类观测。"}</p>{report.data !== null && children(report.data)}</>;
}
function Pages<T>({ items, label, search, children }: { items: T[]; label: string; search: (item: T) => string; children: (item: T, index: number) => ReactNode }) {
  const [query, setQuery] = useState(""); const [page, setPage] = useState(0);
  const filtered = useMemo(() => items.filter(item => search(item).toLowerCase().includes(query.toLowerCase().trim())), [items, query, search]);
  const pages = Math.max(1, Math.ceil(filtered.length / 50)); const current = Math.min(page, pages - 1);
  return <><label>搜索{label}<input aria-label={"搜索" + label} value={query} onChange={event => { setQuery(event.target.value); setPage(0); }}/></label>
    <p>{label} {filtered.length} 条 · 第 {current + 1}／{pages} 页。</p>
    {pages > 1 && <div className="draft-actions"><button type="button" disabled={current === 0} onClick={() => setPage(current - 1)}>{label}上一页</button><button type="button" disabled={current + 1 === pages} onClick={() => setPage(current + 1)}>{label}下一页</button></div>}
    <div className="live-table" tabIndex={0} role="region" aria-label={label}><ul>{filtered.slice(current * 50, (current + 1) * 50).map((item, index) => <li key={index}>{children(item, index)}</li>)}</ul></div>
    {!filtered.length && <p>没有符合条件的记录。</p>}</>;
}
const runSearch = (row: LiveRun) => row.map + " " + row.difficulty + " " + (resultLabels[row.result] || row.result);
const findingSearch = (row: LiveFinding) => [row.name, row.rarity, row.map, row.boss, row.piece].join(" ");

function RunDetail({ row }: { row: LiveRun }) {
  return <><strong>{row.map || "地图未知"}</strong> · {row.difficulty || "难度未知"} · {resultLabels[row.result] || "未知"} · {show(row.dur)} 秒{row.partial !== false && " · 部分记录"}
    <details><summary>展开跑图详情</summary><p>开始：{time(row.t0)}；结束：{time(row.t1)}</p>
      <Values values={[["角色等级", row.level], ["波次", `${show(row.wave)}／${show(row.waves)}`], ["exp", row.exp], ["gold", row.gold], ["死亡次数", row.deaths], ["dmg", row.damage.dmg], ["hits", row.damage.hits], ["crits", row.damage.crits], ["kills", row.damage.kills]]}/>
      <Values values={Object.entries(row.loot).map(([name, amount]) => ["掉落 " + name, amount])}/>
      <p>伤害记录：{row.damage.partial === false ? "来源声明完整" : "完整性未知或部分采集"}。</p>
      {row.damage.sources.map((source, index) => <p key={index}>{source.name || "未知来源"} · {source.actor} · 伤害 {show(source.dmg)} · 命中 {show(source.hits)} · 暴击 {show(source.crits)} · 击杀 {show(source.kills)}</p>)}
      {row.finds.length > 0 && <><h4>本轮特殊掉落</h4><ul>{row.finds.map((item, index) => <li key={index}>{item.name} · {item.rarity}{item.ancient ? " · 远古" : ""}{item.black_mist ? " · 黑雾" : ""} · {item.status || "状态未知"}</li>)}</ul></>}
    </details></>;
}
function RunData({ data }: { data: LiveRuns }) {
  const [map, setMap] = useState("all");
  const records = useMemo(() => data.records.filter(row => map === "all" || row.map === map), [data.records, map]);
  return <><h3>完整跑图记录</h3><p className="muted">速率使用收到的完整记录与总耗时。不同构筑、加成和等待条件可能不同，这些汇总不能证明最优地图。</p>
    <Values values={Object.entries(data.rates)}/><p>当前数据源提供 {data.total} 条历史记录。未采集的历史不会补成零。</p>
    {data.live && <details><summary>当前跑图</summary><RunDetail row={data.live}/></details>}
    <label>历史地图<select aria-label="历史地图" value={map} onChange={event => setMap(event.target.value)}><option value="all">全部地图</option>{[...new Set(data.records.map(row => row.map))].map(name => <option key={name} value={name}>{name || "未知地图"}</option>)}</select></label>
    <Pages items={records} label="跑图记录" search={runSearch}>{row => <RunDetail row={row}/>}</Pages>
    <details><summary>按地图汇总当前记录窗口</summary><div className="live-table"><table><thead><tr><th>地图</th><th>难度</th><th>完整记录</th><th>总耗时（秒）</th><th>经验／秒</th><th>金币／秒</th></tr></thead><tbody>{data.window_maps.map((row, index) => <tr key={index}><td>{row.map}</td><td>{row.difficulty}</td><td>{row.runs}</td><td>{show(row.dur)}</td><td>{show(row.exp_s)}</td><td>{show(row.gold_s)}</td></tr>)}</tbody></table></div></details>
  </>;
}
export function RunReports({ report }: { report: LocalReport<LiveRuns> }) { return <Report report={report}>{data => <RunData data={data}/>}</Report>; }

export function CombatReports({ report }: { report: LocalReport<LiveCombat> }) {
  return <><h3>实战伤害计数</h3><p className="notice">这些统计来自采集端提供的伤害事件。完整窗口不足 10 秒或 60 秒时，对应 DPS 保留未知。数据源需要记录实际伤害。</p>
    <Report report={report}>{data => <><Values values={Object.entries(data.live)}/><h4>采集会话</h4><p>开始：{time(data.session.since)} · {data.session.partial ? "部分记录" : "覆盖整个会话"}</p>
      <Values values={(["dmg", "hits", "crits", "kills", "active", "dur"] as const).map(name => [name, data.session[name]])}/>
      <Pages items={data.session.sources} label="伤害来源" search={source => source.name + " " + source.actor}>{source => <>{source.name || "未知来源"} · {source.actor}<Values values={(["dmg", "hits", "crits", "kills"] as const).map(name => [name, source[name]])}/></>}</Pages>
    </>}</Report></>;
}

function LineageData({ data }: { data: LiveLineage }) {
  const [group, setGroup] = useState<"all" | "auto" | "manual">("all");
  const [kind, setKind] = useState<"draws" | "finds" | "market">("draws");
  const stats = data.gamble[group];
  const records = useMemo(() => data[kind].filter(row => kind !== "draws" || group === "all" || row.how === group), [data, kind, group]);
  return <><label>记录来源<select aria-label="记录来源" value={group} onChange={event => setGroup(event.target.value as typeof group)}><option value="all">全部</option><option value="manual">手动来源</option><option value="auto">自动来源标签</option></select></label>
    <Values values={[["draws", stats.draws], ["shards", stats.shards]]}/>
    <Values values={stats.rarities.map(row => [row.rarity, `${row.count} 次 · 观测占比 ${(row.frequency * 100).toFixed(1)}%`])}/>
    <Values values={(["top", "ancient", "black_mist"] as const).map(name => [name, `${stats[name].k}／${stats[name].n} · ${stats[name].rate === null ? "占比未知" : (stats[name].rate! * 100).toFixed(1) + "%"}`])}/>
    <details><summary>按部位统计</summary>{Object.entries(stats.pieces).map(([name, values]) => <div key={name}><h4>{name}</h4><Values values={Object.entries(values)}/></div>)}</details>
    <label>血脉记录类型<select aria-label="血脉记录类型" value={kind} onChange={event => setKind(event.target.value as typeof kind)}><option value="draws">抽取记录</option><option value="finds">特殊掉落</option><option value="market">来源市场标记</option></select></label>
    <Pages items={records} label="血脉记录" search={findingSearch}>{row => <>{row.name || "未知物品"} · {row.rarity}{row.ancient ? " · 远古" : ""}{row.black_mist ? " · 黑雾" : ""} · {time(row.time)} · {row.map} · {row.boss} · 消耗 {show(row.price)}</>}</Pages>
  </>;
}
export function LineageReports({ report }: { report: LocalReport<LiveLineage> }) {
  return <><h3>血脉与抽取记录</h3><p className="notice">占比只描述收到的样本，不代表下一次抽取概率或运气评分。未知标记不计入对应分母。来源标签不会启动游戏操作。</p><Report report={report}>{data => <LineageData data={data}/>}</Report></>;
}
export function LoadoutReports({ report }: { report: LocalReport<LiveLoadouts> }) {
  return <><h3>配装资料</h3><p className="muted">查看五个配装位置中的技能、装备和缺失记录。配装资料需要采集端提供，不会改变游戏装备。</p><Report report={report}>{data => <><p>当前配装：{show(data.in_use)}</p>{data.slots.map(row => <details key={row.slot}><summary>{row.slot} · {row.name || (row.empty === null ? "未采集" : "未命名配装")}{row.empty ? " · 空" : ""}{row.worn ? " · 当前使用" : ""}</summary><h4>技能</h4><ul>{row.abilities.map((skill, index) => <li key={index}>{labels[skill.role] || skill.role} · {skill.name || skill.key}</li>)}</ul><h4>装备</h4><ul>{row.gear.map((item, index) => <li key={index}>{item.slot} · {item.name} · {item.rarity}</li>)}</ul><h4>缺失记录</h4><ul>{row.missing.map((item, index) => <li key={index}>{item.name} · {{ storage: "位于仓库", gone: "当前未持有", locked: "已锁定" }[item.reason] || "需要核对"}</li>)}</ul></details>)}</>}</Report></>;
}
export function StatusReports({ report }: { report: LocalReport<LiveStatus> }) {
  return <><h3>采集状态与资料目录</h3><p className="muted">目录只提供来源说明，不证明地图已解锁、物品已持有或效果机制已验证。</p><Report report={report}>{data => <><p>采集端版本：{data.producer_version || "未知"}</p><Values values={Object.entries(data.collection_coverage)}/>
    <details><summary>地图与进入材料</summary><Pages items={data.catalogs.maps} label="地图资料" search={row => row.name + " " + row.key}>{row => <>{row.name || row.key} · {row.type} · 前置 {row.prerequisite || "未知"}<ul>{row.entry.map((part, index) => <li key={index}>{part.item} × {show(part.amount)} · {part.difficulties.join("、")}</li>)}</ul></>}</Pages></details>
    <details><summary>药剂与配方</summary><Pages items={data.catalogs.potions} label="药剂资料" search={row => row.name + " " + row.key}>{row => <>{row.name || row.key}<p>{row.description}</p><p>配方产量：{show(row.recipe.quantity)}</p><ul>{row.recipe.ingredients.map((part, index) => <li key={index}>{part.name || part.key} × {show(part.amount)}</li>)}</ul></>}</Pages></details>
    <details><summary>词条池、宝石与符文资料</summary>{Object.entries(data.catalogs.affix_pools).map(([name, values]) => <p key={name}>{name}：{values.join("、")}</p>)}<p>宝石类型：{data.catalogs.gem_kinds.join("、") || "未知"}</p><p>符文稀有度：{data.catalogs.rune_rarities.join("、") || "未知"}</p></details>
    <details><summary>采集事件</summary><ul>{data.events.map((row, index) => <li key={index}>{row.kind} · {row.action} · {row.ok === null ? "结果未知" : row.ok ? "成功" : "失败"} · {row.map}</li>)}</ul></details>
  </>}</Report></>;
}
