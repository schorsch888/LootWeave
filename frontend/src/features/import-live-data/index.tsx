import { useEffect, useMemo, useRef, useState } from "react";
import { api, newId } from "../../shared/api";
import type { ExternalObservation, Snapshot } from "../../shared/api";
import { LiveOverview } from "./overview";

type Props = { disabled: boolean; onBusyChange: (busy: boolean) => void; onError: (message: string) => void; onInvalidate: () => void; onDraft: (facts: Snapshot, observation: ExternalObservation) => void };
const containers: Record<string, string> = { equipment: "身上装备", inventory: "背包", storage: "仓库", carriage: "马车" };
const blockedLabels: Record<string, string> = { not_equipment: "非装备", instance_unavailable: "实例未读取", affix_hash_failed: "词条校验失败", affixes_unavailable: "词条未读取", affix_unverified: "词条待核对", settlement_pending: "等待结算", settlement_unverified: "结算状态待核对", duplicate_instance: "实例重复" };
const classLabels: Record<string, string> = { sorcerer: "法师", warrior: "战士", hunter: "猎人", necromancer: "死灵法师" };
const PAGE_SIZE = 50;

export function ImportLiveData({ disabled, onBusyChange, onError, onInvalidate, onDraft }: Props) {
  const [producerId, setProducerId] = useState("desktop");
  const [edition, setEdition] = useState("1.0.0i");
  const [mode, setMode] = useState("online");
  const [classId, setClassId] = useState("sorcerer");
  const [scopeConfirmed, setScopeConfirmed] = useState(false);
  const [preview, setPreview] = useState<ExternalObservation>();
  const [candidateId, setCandidateId] = useState("");
  const [ringSlot, setRingSlot] = useState("ring1");
  const [container, setContainer] = useState("all");
  const [query, setQuery] = useState("");
  const [rarity, setRarity] = useState("all");
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const fileInput = useRef<HTMLInputElement | null>(null);
  const generation = useRef(0);
  const pending = useRef<AbortController | undefined>(undefined);
  const background = useRef(false);

  useEffect(() => () => { generation.current++; pending.current?.abort(); }, []);
  const cancelBackground = () => {
    if (!background.current) return;
    generation.current++; pending.current?.abort(); pending.current = undefined;
    background.current = false; setReading(false);
  };
  const invalidate = () => {
    generation.current++; pending.current?.abort(); setPreview(undefined); setCandidateId(""); setPage(0);
    pending.current = undefined; background.current = false; setReading(false); setAutoRefresh(false);
    setScopeConfirmed(false); onInvalidate();
  };
  const run = async (kind: "preview" | "draft", monitor = false) => {
    if (pending.current || busy || disabled || !scopeConfirmed || kind === "draft" && (!preview || !candidateId)) return;
    const attempt = ++generation.current;
    const controller = new AbortController(); pending.current = controller;
    background.current = monitor;
    if (kind === "preview") setReading(true);
    if (!monitor) { setBusy(true); onBusyChange(true); onError(""); }
    if (kind === "preview" && !monitor) { setAutoRefresh(false); setPreview(undefined); setCandidateId(""); setPage(0); onInvalidate(); }
    try {
      if (kind === "preview") {
        type Unchanged = { unchanged: true } & Pick<ExternalObservation, "observation_id" | "source" | "capture_context" | "raw_text">;
        const result = await api<ExternalObservation | Unchanged>("profile/imports/live/read", {
          observation_id: newId("live"), producer_id: producerId, scope_confirmed: scopeConfirmed, class_id: classId,
          ...(monitor && preview ? { previous_content_hash: preview.source.content_hash } : {}),
          context: { game_id: "deskrawl", edition, game_build: "25690430", mode, season: "not_applicable", ruleset_id: "deskrawl-25690430", content_entitlements: [] },
        }, { signal: controller.signal });
        if (attempt === generation.current) {
          if ("unchanged" in result) {
            if (!preview || result.source.content_hash !== preview.source.content_hash) throw new Error("数据来源已变化，请刷新预览后重新载入。");
            setPreview({ ...preview, ...result });
          } else setPreview(result);
        }
      } else {
        const candidate = preview!.items.find(item => item.id === candidateId);
        const result = await api<{ observation_id: string; response_hash: string; facts: Snapshot }>("profile/imports/live/draft", {
          observation_id: preview!.observation_id, candidate_id: candidateId,
          ...(candidate?.slot === "ring" ? { target_slot: ringSlot } : {}),
        }, { signal: controller.signal });
        if (attempt === generation.current) {
          if (result.observation_id !== preview!.observation_id || result.response_hash !== preview!.source.response_hash)
            throw new Error("数据来源已变化，请刷新预览后重新载入。");
          onDraft(result.facts, preview!);
        }
      }
    } catch (error) {
      if (!controller.signal.aborted && attempt === generation.current) {
        setAutoRefresh(false);
        onError((monitor ? "持续刷新已停止，保留上次预览。" : "") + (error instanceof Error ? error.message : "数据读取失败。"));
      }
    } finally {
      if (attempt === generation.current) {
        setReading(false); pending.current = undefined; background.current = false;
        if (!monitor) { setBusy(false); onBusyChange(false); }
      }
    }
  };
  useEffect(() => {
    if (!autoRefresh || !preview || disabled || busy || !scopeConfirmed) { cancelBackground(); return; }
    let timer: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      clearTimeout(timer);
      if (document.hidden) { cancelBackground(); return; }
      timer = setTimeout(() => void run("preview", true), 2000);
    };
    arm(); document.addEventListener("visibilitychange", arm);
    return () => { clearTimeout(timer); document.removeEventListener("visibilitychange", arm); };
  }, [autoRefresh, preview, disabled, busy, scopeConfirmed]);
  const visible = useMemo(() => (preview?.items ?? []).filter(item => (container === "all" || item.container === container)
    && (rarity === "all" || item.rarity === rarity)
    && (item.name + " " + item.template_id).toLowerCase().includes(query.toLowerCase().trim())), [preview?.items, container, rarity, query]);
  const selected = preview?.items.find(item => item.id === candidateId);
  const pages = Math.max(1, Math.ceil(visible.length / PAGE_SIZE));
  const currentPage = Math.min(page, pages - 1);
  const displayed = visible.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);
  const rarities = [...new Set(preview?.items.map(item => item.rarity).filter(Boolean) ?? [])];
  const importFile = async (file?: File) => {
    if (!file || busy || disabled) return;
    invalidate(); setBusy(true); onBusyChange(true); onError("");
    try {
      if (file.size > 4 * 1024 * 1024) throw new Error("观测文件超过 4 MiB 上限。");
      const result = await api<{ producer_id: string }>("profile/live/samples", JSON.parse(await file.text()));
      setProducerId(result.producer_id);
    } catch (error) { onError(error instanceof Error ? error.message : "观测文件读取失败。"); }
    finally { setBusy(false); onBusyChange(false); if (fileInput.current) fileInput.current.value = ""; }
  };

  return <section className="panel" aria-label="实时 API 数据">
    <div className="section-heading"><div><span className="eyebrow">LIVE DATA</span><h2>读取 LootWeave 实时数据</h2></div><span className="tag">本机 API</span></div>
    <p>读取我们本机接口已接收的观测。选择候选装备后，核对完整构筑并保存快照。</p>
    <fieldset disabled={disabled || busy} className="draft-controls">
      <div className="fields">
        <label>数据源标识<input value={producerId} onChange={event => { invalidate(); setProducerId(event.target.value); }}/></label>
        <label>发行版本<input value={edition} onChange={event => { invalidate(); setEdition(event.target.value); }}/></label>
        <label>角色模式<select aria-label="角色模式" value={mode} onChange={event => { invalidate(); setMode(event.target.value); }}><option value="online">线上</option><option value="local">离线</option></select></label>
        <label>角色职业<select aria-label="角色职业" value={classId} onChange={event => { invalidate(); setClassId(event.target.value); }}>{Object.entries(classLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
      </div>
      <p className="muted">采集端需要向 LootWeave 提供观测。当前支持 lootweave-live/1 协议；接口本身不会自动读取游戏。没有采集数据时，可以使用截图 OCR。</p>
      <label>载入观测文件<input ref={fileInput} type="file" accept="application/json,.json" onChange={event => void importFile(event.target.files?.[0])}/></label>
      <label className="check"><input type="checkbox" checked={scopeConfirmed} onChange={event => { invalidate(); setScopeConfirmed(event.target.checked); }}/>我已核对游戏构建 25690430、发行版本、模式和职业。</label>
      <button type="button" disabled={reading || !scopeConfirmed || !/^[a-zA-Z0-9_.-]{1,100}$/.test(producerId)} onClick={() => void run("preview")}>{busy ? "正在读取…" : "读取／刷新当前数据"}</button>
    </fieldset>
    {preview && <>
      <p role="status">{preview.character.name || classLabels[preview.character.class_id]} · 等级 {preview.character.level} · 共 {preview.items.length} 条物品记录。采集时间：<time dateTime={preview.source.captured_at}>{new Date(preview.source.captured_at).toLocaleString()}</time></p>
      <label className="check"><input type="checkbox" disabled={disabled || busy} checked={autoRefresh} onChange={event => { if (!event.target.checked) cancelBackground(); else setCandidateId(""); setAutoRefresh(event.target.checked); }}/>持续刷新（每次读取完成后等待 2 秒）</label>
      <p className="muted">{autoRefresh ? reading ? "正在更新预览。" : "持续刷新中。页面隐藏时暂停。" : "持续刷新已暂停。"}选择候选会暂停刷新。已载入的草稿保留采集时的数据。</p>
      <LiveOverview data={preview.overview} character={preview.character} reports={preview.telemetry} buildSources={preview.build_sources}/>
      <p className="muted">{Object.entries(preview.coverage).map(([name, status]) => `${containers[name]}：${status === "enabled" ? "已读取" : status === "partial" ? "部分读取" : "未读取"}`).join("；")}。</p>
      <div className="notice">词条单位、特殊效果、镶嵌物和部分构筑来源仍需核对。数据保留为部分覆盖，未读取的内容保留未知。</div>
      <div className="fields">
        <label>物品位置<select aria-label="物品位置" value={container} onChange={event => { setContainer(event.target.value); setPage(0); }}><option value="all">全部位置</option>{Object.entries(containers).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label>稀有度<select aria-label="稀有度" value={rarity} onChange={event => { setRarity(event.target.value); setPage(0); }}><option value="all">全部稀有度</option>{rarities.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
        <label>搜索装备<input value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} placeholder="名称或模板标识"/></label>
      </div>
      <p>筛选结果 {visible.length} 条{visible.length > PAGE_SIZE ? ` · 第 ${currentPage + 1}／${pages} 页` : ""}。</p>
      {visible.length > PAGE_SIZE && <div className="draft-actions"><button type="button" disabled={disabled || busy || currentPage === 0} onClick={() => setPage(currentPage - 1)}>上一页</button><button type="button" disabled={disabled || busy || currentPage + 1 === pages} onClick={() => setPage(currentPage + 1)}>下一页</button></div>}
      <div className="live-table" tabIndex={0} role="region" aria-label="持有物品记录"><table><thead><tr><th>候选</th><th>装备</th><th>位置</th><th>稀有度</th><th>状态</th></tr></thead><tbody>{displayed.map((item, index) => <tr key={item.id + "/" + index}>
        <td><input type="radio" name="live-candidate" aria-label={"选择 " + item.name} disabled={disabled || busy || item.blocked.length > 0 || item.container === "equipment"} checked={candidateId === item.id} onChange={() => { cancelBackground(); setAutoRefresh(false); setCandidateId(item.id); onInvalidate(); }}/></td>
        <td>{item.name}<details><summary>查看词条</summary>{item.affixes.length ? item.affixes.map(affix => <p key={affix.id}>{affix.name}：{affix.value}（{affix.unit === "unverified" ? "单位待核对" : affix.unit}）{affix.roll.quality !== null ? ` · 区间位置 ${(affix.roll.quality * 100).toFixed(1)}%` : ""}</p>) : <p>没有已读取词条。</p>}<p>物品等级：{item.item_level ?? "未知"}；强化：{item.upgrade_level ?? "未知"}；宝石槽：{item.sockets ?? "未知"}</p>{item.armor !== null && <p>护甲：{item.armor}</p>}{item.weapon.damage !== undefined && <p>武器伤害：{item.weapon.damage ?? "未知"}；速度：{item.weapon.speed ?? "未知"}；武器 DPS：{item.weapon.dps ?? "未知"}</p>}{item.effect_description && <p>效果说明（待核对）：{item.effect_description}</p>}<p>已采集镶嵌物：{item.embedded_items.length}；已用槽位：{item.sockets_used ?? "未知"}。</p>{item.embedded_items.map(source => <p key={source.id}>{source.name || source.id} · 等级 {source.rank ?? source.level ?? "未知"}</p>)}</details></td>
        <td>{containers[item.container]}{item.page !== null ? " · 页 " + (item.page + 1) : ""}</td><td>{item.rarity}{item.ancient ? " · 远古" : ""}{item.black_mist ? " · 黑雾" : ""}</td>
        <td>{item.locked ? "已锁定；" : ""}{item.blocked.length ? item.blocked.map(reason => blockedLabels[reason] || "待核对").join("、") : item.container === "equipment" ? "当前装备" : "可作为候选"}</td>
      </tr>)}</tbody></table></div>
      {!visible.length && <p>没有符合筛选条件的物品。</p>}
      {selected && <p>已选候选：<strong>{selected.name}</strong>（{containers[selected.container]}）</p>}
      {selected?.slot === "ring" && <label>戒指比较槽位<select aria-label="戒指比较槽位" disabled={disabled || busy} value={ringSlot} onChange={event => { setRingSlot(event.target.value); onInvalidate(); }}><option value="ring1">戒指 1</option><option value="ring2">戒指 2</option></select></label>}
      <button type="button" disabled={disabled || busy || !selected || selected.blocked.length > 0 || selected.container === "equipment"} onClick={() => void run("draft")}>载入候选与当前构筑</button>
      <p className="muted">载入后请在下方核对并确认保存。刷新预览会保留已载入的草稿，并要求重新载入核对。</p>
    </>}
  </section>;
}
