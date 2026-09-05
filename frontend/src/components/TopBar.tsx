import type { SystemStatus, TraceState } from "../state/useTraceMachine";
import { StageProgress } from "./StageProgress";
import styles from "./TopBar.module.css";

const STATUS_LABEL: Record<SystemStatus, string> = {
  online: "SYSTEM ONLINE",
  active: "TRACE ACTIVE",
  anchoring: "ANCHORING",
  verified: "VERIFIED",
  halted: "INVESTIGATION HALTED",
};

const STATUS_DOT_CLASS: Record<SystemStatus, string> = {
  online: styles.dotOnline,
  active: styles.dotActive,
  anchoring: styles.dotAmber,
  verified: styles.dotVerified,
  halted: styles.dotHalted,
};

export function TopBar({
  state,
  onSelectStage,
}: {
  state: TraceState;
  onSelectStage: (stage: TraceState["currentStage"]) => void;
}) {
  return (
    <header className={styles.bar}>
      <div className={styles.brand}>
        <span className={styles.wordmark}>TRACE</span>
        <span className={styles.subtitle}>MEDIA PROVENANCE SYSTEM</span>
      </div>

      <StageProgress
        currentStage={state.currentStage}
        highestReachedStage={state.highestReachedStage}
        onSelectStage={onSelectStage}
      />

      <div className={styles.status}>
        <span className={`${styles.dot} ${STATUS_DOT_CLASS[state.systemStatus]}`} />
        <span className={styles.statusLabel}>{STATUS_LABEL[state.systemStatus]}</span>
        <span className={styles.network}>POLYGON AMOY</span>
      </div>
    </header>
  );
}
