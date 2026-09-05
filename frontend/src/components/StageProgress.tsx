import { TRACE_STAGE_LABELS } from "../api/types";
import type { TraceStageId } from "../api/types";
import styles from "./StageProgress.module.css";

const STAGES: TraceStageId[] = [1, 2, 3, 4, 5, 6];

export function StageProgress({
  currentStage,
  highestReachedStage,
  onSelectStage,
}: {
  currentStage: TraceStageId;
  highestReachedStage: TraceStageId;
  onSelectStage: (stage: TraceStageId) => void;
}) {
  return (
    <ol className={styles.track} aria-label="Investigation progress">
      {STAGES.map((stage, i) => {
        const state =
          stage < currentStage
            ? "complete"
            : stage === currentStage
              ? "current"
              : "upcoming";
        const reachable = stage <= highestReachedStage;

        return (
          <li key={stage} className={styles.item}>
            <button
              type="button"
              className={`${styles.node} ${styles[state]}`}
              disabled={!reachable}
              aria-current={state === "current" ? "step" : undefined}
              onClick={() => reachable && onSelectStage(stage)}
            >
              <span className={styles.num}>{String(stage).padStart(2, "0")}</span>
              <span className={styles.label}>{TRACE_STAGE_LABELS[stage]}</span>
            </button>
            {i < STAGES.length - 1 && (
              <span
                className={`${styles.connector} ${
                  stage < currentStage ? styles.connectorDone : ""
                }`}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
