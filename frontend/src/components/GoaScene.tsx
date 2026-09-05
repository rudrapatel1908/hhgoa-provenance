import type { TraceStageId } from "../api/types";
import styles from "./GoaScene.module.css";

// Per-stage color tint, layered atop the fixed photo -- preserves the
// "environment subtly evolves with the investigation" idea from the
// original SVG scene, without needing multiple photos. Idle -> more
// focused -> deeper (search/anchor) -> calm again on verify.
const STAGE_TINT: Record<TraceStageId, string> = {
  1: "rgba(22, 38, 31, 0.18)",
  2: "rgba(22, 38, 31, 0.28)",
  3: "rgba(18, 34, 40, 0.38)",
  4: "rgba(16, 32, 30, 0.42)",
  5: "rgba(14, 26, 24, 0.5)",
  6: "rgba(22, 45, 36, 0.22)",
};

export function GoaScene({ stage }: { stage: TraceStageId }) {
  return (
    <div className={styles.scene} aria-hidden="true">
      <div className={styles.photo} />
      <div className={styles.tint} style={{ background: STAGE_TINT[stage] }} />
      <div className={styles.vignette} />
    </div>
  );
}
