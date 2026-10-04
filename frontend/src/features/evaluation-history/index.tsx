import { useEffect, useRef, useState } from "react";
import { api } from "../../shared/api";
import type { EvaluationResult } from "../../shared/api";

type Props = {
  refreshKey: string;
  onSelect: (result: EvaluationResult) => void;
  onError: (message: string) => void;
};

type EvaluationSummary = Pick<EvaluationResult, "evaluation_id" | "retention" | "pin">;
type HistoryResponse = { evaluations: EvaluationSummary[]; limit: number };

export function EvaluationHistory({ refreshKey, onSelect, onError }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [loadingId, setLoadingId] = useState("");
  const [evaluations, setEvaluations] = useState<EvaluationSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const onErrorRef = useRef(onError);
  const requestId = useRef(0);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    if (!open) return;
    const currentRequest = ++requestId.current;
    setBusy(true);
    api<HistoryResponse>("evaluation/evaluations")
      .then(result => {
        if (requestId.current === currentRequest) {
          setEvaluations(result.evaluations.slice(0, 100));
          setLoaded(true);
        }
      })
      .catch(error => {
        if (requestId.current === currentRequest) {
          onErrorRef.current(error instanceof Error ? error.message : "读取历史评估失败。");
        }
      })
      .finally(() => {
        if (requestId.current === currentRequest) setBusy(false);
      });
    return () => {
      if (requestId.current === currentRequest) requestId.current++;
    };
  }, [open, refreshKey]);

  const selectEvaluation = async (evaluationId: string) => {
    setLoadingId(evaluationId);
    try {
      const result = await api<EvaluationResult>(`evaluation/evaluations/${encodeURIComponent(evaluationId)}`);
      onSelect(result);
    } catch (error) {
      onErrorRef.current(error instanceof Error ? error.message : "读取冻结评估失败。");
    } finally {
      setLoadingId("");
    }
  };

  return <section className="panel">
    <details onToggle={event => setOpen(event.currentTarget.open)}>
      <summary>查看历史冻结评估</summary>
      <p className="muted">读取的是保存的输入版本，不使用当前编辑草稿。</p>
      <div aria-live="polite">
        {busy && <p className="muted">正在读取历史评估…</p>}
        {!busy && loaded && evaluations.length === 0 && <p className="muted">还没有保存的评估。</p>}
        {evaluations.map(evaluation => {
          const context = evaluation.pin.context;
          const isLoading = loadingId === evaluation.evaluation_id;
          return <article className="reason" key={evaluation.evaluation_id}>
            <p><strong>{evaluation.retention}</strong></p>
            <p>游戏：{context.game_id} · 版本：{context.edition} / {context.game_build}</p>
            <p>模式：{context.mode} · 赛季：{context.season} · 规则集：{context.ruleset_id}</p>
            <p>档案修订：{evaluation.pin.profile_revision} · 知识包版本：{evaluation.pin.pack_version}</p>
            <p>评估器版本：{evaluation.pin.evaluator_version}</p>
            <p className="muted">评估 ID：{evaluation.evaluation_id}</p>
            <button type="button" onClick={() => void selectEvaluation(evaluation.evaluation_id)} disabled={Boolean(loadingId)}>
              {isLoading ? "读取中…" : "查看这份冻结结果"}
            </button>
          </article>;
        })}
      </div>
    </details>
  </section>;
}
