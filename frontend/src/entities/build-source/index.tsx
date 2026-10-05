import { isExactCount } from "../../shared/api";
import type { Source } from "../../shared/api";

type SourceListProps = {
  title: string;
  sources: Source[];
  evidenceIds: string[];
  ranks?: boolean;
  levels?: boolean;
  setIds?: boolean;
  defaultActor?: "hero" | "companion";
  onChange: (sources: Source[]) => void;
};

function newId(prefix: string) {
  return `${prefix}-${crypto.randomUUID()}`;
}

function listValue(value: string): string[] {
  return value.split(",").map(part => part.trim()).filter(Boolean);
}

export function SourceFields({ source, ranks, setIds, defaultActor, levels = false, levelLabel = "仆从实际等级", onChange, onDelete }: {
  source: Source;
  ranks: boolean;
  levels?: boolean;
  levelLabel?: string;
  setIds: boolean;
  defaultActor: "hero" | "companion";
  onChange: (source: Source) => void;
  onDelete: () => void;
}) {
  return <div className="source-list">
    <label>标识（稳定英文 ID）<input value={source.id} onChange={event => onChange({ ...source, id: event.target.value })} /></label>
    {ranks && <label>等级（须 ≥ 0）<input type="number" min="0" value={source.rank ?? ""}
      onChange={event => {
        const raw = event.target.value;
        if (raw === "") {
          const { rank: _rank, ...rest } = source;
          onChange(rest);
        } else {
          const rank = Number(raw);
          if (Number.isFinite(rank)) onChange({ ...source, rank });
        }
      }} /></label>}
    {levels && <label>{levelLabel}<input aria-label={levelLabel} type="number" min="1" step="1"
      value={Number.isSafeInteger(source.level) && (source.level ?? 0) > 0 ? source.level : ""}
      onChange={event => onChange({ ...source, level: event.target.value === "" ? undefined
        : isExactCount(event.target.value) && Number(event.target.value) > 0 ? Number(event.target.value) : Number.NaN })} /></label>}
    {(source.actor ?? defaultActor) === "companion" && !levels && <label>仆从归属 ID<input aria-label="仆从归属 ID"
      value={source.companion_id ?? ""} onChange={event => onChange({ ...source, companion_id: event.target.value || undefined })} /></label>}
    <label>明确效果（逗号分隔，不推断）<input value={source.effects.join(", ")}
      onChange={event => onChange({ ...source, effects: listValue(event.target.value) })} /></label>
    <label>作用者<select value={source.actor ?? defaultActor}
      onChange={event => {
        const { companion_id, ...rest } = source;
        onChange({ ...rest, actor: event.target.value, ...(event.target.value === "companion" ? { companion_id } : {}) });
      }}>
      <option value="hero">角色本人</option><option value="companion">仆从</option>
    </select></label>
    {setIds && <label>符文组 ID（可选）<input value={source.set_id ?? ""}
      onChange={event => onChange({ ...source, set_id: event.target.value || undefined })} /></label>}
    <small className="muted">输入来源证据：{source.evidence_ids.join("、") || "暂无"}</small>
    <button type="button" onClick={onDelete}>删除</button>
  </div>;
}

export function SourceList({ title, sources, evidenceIds, ranks = false, levels = false, setIds = false, defaultActor = "hero", onChange }: SourceListProps) {
  const replace = (index: number, next: Source) => onChange(sources.map((source, i) => i === index ? next : source));
  const remove = (index: number) => onChange(sources.filter((_, i) => i !== index));
  const add = () => onChange([...sources, {
    id: newId("source"), effects: [], evidence_ids: [...evidenceIds], actor: defaultActor, ...(ranks ? { rank: 0 } : {}),
  }]);

  return <details>
    <summary>{title}（{sources.length}）</summary>
    <div className="source-list">
      {sources.map((source, index) => <SourceFields key={index} source={source} ranks={ranks} levels={levels} setIds={setIds} defaultActor={defaultActor}
        onChange={next => replace(index, next)} onDelete={() => remove(index)} />)}
      <button type="button" onClick={add}>添加{title}</button>
    </div>
  </details>;
}
