import { GoaScene } from "./components/GoaScene";
import { TopBar } from "./components/TopBar";
import { Stage01Lock } from "./stages/Stage01Lock";
import { useTraceMachine } from "./state/useTraceMachine";
import { streamDiscover, streamVerify, streamRegister } from "./api/client";
import type { DiscoveryResult, PipelineResult } from "./api/types";
import styles from "./App.module.css";

// Default Amoy explorer base -- matches the project's documented default
// (contracts/COMPILATION.md, README). If you deployed against a
// different EXPLORER_BASE_URL in .env, this link will still point at
// Amoy specifically; adjust here if that ever changes.
const EXPLORER_TX_BASE = "https://amoy.polygonscan.com/tx/";

export default function App() {
  const {
    state,
    setImage,
    goToStage,
    beginRun,
    recordStage,
    completeRun,
    haltRun,
  } = useTraceMachine();

  async function handleBegin() {
    if (!state.image) return;
    beginRun("discover");
    try {
      await streamDiscover<DiscoveryResult>(state.image, {
        onStage: recordStage,
        onResult: (result) => completeRun(result as unknown as { final_status: string }),
        onError: () => haltRun(),
      });
    } catch {
      haltRun();
    }
  }

  async function handleVerify() {
    const match = state.discoveredMatch as any;
    if (!state.image || !match?.candidate?.url) return;
    beginRun("verify");
    try {
      await streamVerify<PipelineResult>(state.image, match.candidate.url, {
        onStage: recordStage,
        onResult: (result) => completeRun(result as unknown as { final_status: string }),
        onError: () => haltRun(),
      });
    } catch {
      haltRun();
    }
  }

  async function handleAnchor() {
    const match = state.discoveredMatch as any;
    if (!state.image || !match?.candidate?.url) return;
    // The one explicit, user-initiated real transaction in the whole
    // app. Nothing upstream of this click can trigger it.
    const confirmed = window.confirm(
      "This will send a REAL transaction on Polygon Amoy and spend testnet POL. Continue?",
    );
    if (!confirmed) return;
    beginRun("register");
    try {
      await streamRegister<PipelineResult>(state.image, match.candidate.url, {
        onStage: recordStage,
        onResult: (result) => completeRun(result as unknown as { final_status: string }),
        onError: () => haltRun(),
      });
    } catch {
      haltRun();
    }
  }

  const match = state.discoveredMatch as any;
  const result = state.lastResult as any;

  const showVerifyCta =
    state.runKind === "discover" &&
    !state.isRunning &&
    state.lastFinalStatus === "discovered" &&
    match;

  const showAnchorSection =
    state.runKind === "verify" &&
    !state.isRunning &&
    (state.lastFinalStatus === "corroborated" || state.lastFinalStatus === "verified");

  const showVerifiedSection =
    state.runKind === "register" && !state.isRunning && state.lastFinalStatus === "on_chain_verified";

  return (
    <div className={styles.app}>
      <TopBar state={state} onSelectStage={goToStage} />
      <main className={styles.viewport}>
        <GoaScene stage={state.currentStage} />

        {state.currentStage === 1 && (
          <Stage01Lock image={state.image} onImageSelected={setImage} onBegin={handleBegin} />
        )}

        {state.currentStage >= 2 && (
          <div className={styles.placeholder}>
            {/* Real-time stage feed -- every line here is a genuine
                StageRecord from the backend for whichever action
                (discover/verify/register) is currently running. */}
            <p className="mono" style={{ color: "#cddccf" }}>
              STAGE {state.currentStage} — {state.stageEvents.length} real event(s) received
              {state.runKind ? ` (${state.runKind})` : ""}
            </p>
            <ul className="mono" style={{ color: "#8a978d", fontSize: "0.8rem" }}>
              {state.stageEvents.map((e, i) => (
                <li key={i}>
                  {e.stage}: {e.status} — {e.detail || e.error}
                </li>
              ))}
            </ul>

            {state.isRunning && (
              <p className="mono" style={{ color: "var(--signal-amber)" }}>
                ● waiting on backend (live search / chain calls can take several seconds)…
              </p>
            )}

            {!state.isRunning && state.lastFinalStatus && (
              <p className="mono" style={{ color: "var(--signal-teal)" }}>
                ✓ RUN COMPLETE — FINAL STATUS: {state.lastFinalStatus.toUpperCase()}
              </p>
            )}

            {/* -------- 04 MATCH FOUND -------- */}
            {match && (
              <div className="mono" style={{ color: "#cddccf", marginTop: 10 }}>
                <div>PLATFORM: {match.platform}</div>
                <div>RANK: #{match.candidate_rank + 1}</div>
                <div>
                  DISTANCE: {match.face_comparison.distance.toFixed(4)} (threshold{" "}
                  {match.face_comparison.threshold})
                </div>
                <div>
                  URL:{" "}
                  <a
                    href={match.candidate.url}
                    target="_blank"
                    rel="noreferrer"
                    style={{ color: "var(--signal-teal)" }}
                  >
                    {match.candidate.url}
                  </a>
                </div>
              </div>
            )}

            {showVerifyCta && (
              <button className={styles.actionBtn} onClick={handleVerify}>
                VERIFY SOURCE →
              </button>
            )}

            {/* -------- 05 PROVENANCE ANCHOR -------- */}
            {showAnchorSection && (
              <div style={{ marginTop: 18, borderTop: "1px solid var(--surface-dark-border)", paddingTop: 14 }}>
                <p className="mono" style={{ color: "var(--signal-amber)" }}>
                  05 — PROVENANCE ANCHOR
                </p>
                <div className="mono" style={{ color: "#cddccf", fontSize: "0.8rem", marginBottom: 10 }}>
                  <div>MANIFEST HASH: {result?.manifest_hash_hex ?? "(pending)"}</div>
                  <div>DRY RUN: {String(result?.dry_run)}</div>
                </div>
                {result?.dry_run && (
                  <p className="mono" style={{ color: "#8a978d", fontSize: "0.78rem" }}>
                    TRANSACTION NOT SENT · POL SAVED
                  </p>
                )}
                <p className="mono" style={{ color: "#8a978d", fontSize: "0.75rem" }}>
                  READY TO ANCHOR — NETWORK: POLYGON AMOY — CHAIN ID: 80002
                  <br />
                  This action writes the verified provenance record on-chain.
                </p>
                <button className={styles.actionBtn} onClick={handleAnchor}>
                  ANCHOR PROVENANCE
                </button>
              </div>
            )}

            {/* -------- 06 ON-CHAIN VERIFIED -------- */}
            {showVerifiedSection && (
              <div style={{ marginTop: 18, borderTop: "1px solid var(--surface-dark-border)", paddingTop: 14 }}>
                <p className="mono" style={{ color: "var(--signal-emerald)" }}>
                  06 — ON-CHAIN VERIFIED · PROVENANCE ESTABLISHED
                </p>
                <div className="mono" style={{ color: "#cddccf", fontSize: "0.8rem" }}>
                  <div>SOURCE: {match?.platform}</div>
                  <div>MANIFEST HASH: {result?.manifest_hash_hex}</div>
                  <div>
                    TRANSACTION:{" "}
                    <a
                      href={`${EXPLORER_TX_BASE}${result?.blockchain?.tx_hash}`}
                      target="_blank"
                      rel="noreferrer"
                      style={{ color: "var(--signal-teal)" }}
                    >
                      {result?.blockchain?.tx_hash}
                    </a>
                  </div>
                  <div>BLOCK: {result?.blockchain?.block_number}</div>
                  <div>NETWORK: Polygon Amoy</div>
                  <div>HASH MATCH: {String(result?.onchain_verification?.hashes_match)}</div>
                </div>
                <ul className="mono" style={{ color: "var(--signal-emerald)", fontSize: "0.78rem", marginTop: 8 }}>
                  <li>✓ SOURCE CORROBORATED</li>
                  <li>✓ MANIFEST COMMITTED</li>
                  <li>✓ TRANSACTION CONFIRMED</li>
                  <li>✓ ON-CHAIN HASH MATCHED</li>
                </ul>
              </div>
            )}
          </div>
        )}
      </main>
    </div>
  );
}
