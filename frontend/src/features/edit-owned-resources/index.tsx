import { isExactCount, newId } from "../../shared/api";
import type { OwnedResources, ResourceCost, Snapshot } from "../../shared/api";

type Balance = OwnedResources["balances"][number];

const coverageLabels: Record<OwnedResources["coverage"], string> = {
  complete: "完整：已核对全部相关材料或货币",
  partial: "部分：仍有材料或货币未核对",
  unknown: "未知：目前无法确认资源数量",
};

const shownAmount = (amount: number) =>
  Number.isSafeInteger(amount) && amount >= 0 ? String(amount) : "";

export function OwnedResourcesEditor({
  facts,
  onChange,
}: {
  facts: Snapshot;
  onChange: (facts: Snapshot) => void;
}) {
  const resources = facts.owned_resources;

  if (!resources) {
    return (
      <section className="panel">
        <h2>持有材料与货币</h2>
        <p className="muted">未扫描不等于空库存。这里记录材料或货币个数，不会修改游戏。</p>
        <button
          type="button"
          onClick={() => onChange({
            ...facts,
            owned_resources: { coverage: "partial", balances: [] },
          })}
        >
          开始核对资源
        </button>
      </section>
    );
  }

  const updateCoverage = (coverage: OwnedResources["coverage"]) => {
    onChange({ ...facts, owned_resources: { ...resources, coverage } });
  };

  const updateBalances = (balances: Balance[]) => {
    onChange({
      ...facts,
      owned_resources: { ...resources, coverage: "partial", balances },
    });
  };

  const updateBalance = (index: number, patch: Partial<ResourceCost>) => {
    updateBalances(resources.balances.map((row, rowIndex) =>
      rowIndex === index ? { ...row, ...patch } : row,
    ));
  };

  return (
    <details className="panel">
      <summary>持有材料与货币（{resources.balances.length} 项）</summary>
      <p className="muted">记录材料或货币个数，不会修改游戏内资源。数量未知时留空，不要填零。</p>
      <label>
        资源核对范围
        <select
          aria-label="资源核对范围"
          value={resources.coverage}
          onChange={event => updateCoverage(event.target.value as OwnedResources["coverage"])}
        >
          {Object.entries(coverageLabels).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      {resources.balances.map((balance, index) => (
        <div className="fields" key={index}>
          <label>
            材料或货币英文 ID
            <input
              aria-label={`第 ${index + 1} 项资源英文 ID`}
              placeholder="例如 crafting_shard"
              value={balance.resource_id}
              onChange={event => updateBalance(index, { resource_id: event.target.value })}
            />
          </label>
          <label>
            当前个数
            <input
              aria-label={`第 ${index + 1} 项资源个数`}
              type="number"
              min="0"
              step="1"
              placeholder="未知时留空"
              value={shownAmount(balance.amount)}
              onChange={event => updateBalance(index, {
                amount: isExactCount(event.target.value) ? Number(event.target.value) : Number.NaN,
              })}
            />
          </label>
          <p className="muted">
            证据 ID：{balance.evidence_ids.length ? balance.evidence_ids.join("、") : "未关联证据"}
          </p>
          <button
            type="button"
            aria-label={`删除资源 ${balance.resource_id || index + 1}`}
            onClick={() => updateBalances(resources.balances.filter((_, rowIndex) => rowIndex !== index))}
          >
            删除
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => updateBalances([
          ...resources.balances,
          {
            resource_id: newId("resource"),
            amount: Number.NaN,
            evidence_ids: [...facts.evidence_ids],
          },
        ])}
      >
        添加材料或货币
      </button>
      <p className="muted">{coverageLabels[resources.coverage]}。添加、删除或编辑资源会将范围改为“部分”。</p>
    </details>
  );
}