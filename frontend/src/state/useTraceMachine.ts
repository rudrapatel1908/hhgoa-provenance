import { useCallback, useState } from "react";
import type { StageRecord, TraceStageId } from "../api/types";
import { BACKEND_STAGE_TO_TRACE_STAGE } from "../api/types";

export type SystemStatus =
  | "online" // idle, ready
  | "active" // a run is in progress
  | "anchoring" // blockchain write in flight
  | "verified" // final success state reached
  | "halted"; // a real failure occurred

export type RunKind = "discover" | "verify" | "register";

export interface TraceState {
  currentStage: TraceStageId;
  highestReachedStage: TraceStageId; // gates which stages are clickable
  systemStatus: SystemStatus;
  image: File | null;
  stageEvents: StageRecord[]; // every real StageRecord received this run, in order
  isRunning: boolean; // true from beginRun() until a result/error event arrives
  lastFinalStatus: string | null; // e.g. "discovered", "on_chain_verified" -- null while running
  lastResult: Record<string, unknown> | null; // full DiscoveryResult/PipelineResult from the "result" SSE event
  discoveredMatch: Record<string, unknown> | null; // persists across the verify/register runs that follow discovery
  runKind: RunKind | null; // which action produced lastResult -- avoids guessing from final_status alone
}

const initialState: TraceState = {
  currentStage: 1,
  highestReachedStage: 1,
  systemStatus: "online",
  image: null,
  stageEvents: [],
  isRunning: false,
  lastFinalStatus: null,
  lastResult: null,
  discoveredMatch: null,
  runKind: null,
};

export function useTraceMachine() {
  const [state, setState] = useState<TraceState>(initialState);

  const setImage = useCallback((image: File | null) => {
    setState((s) => ({ ...s, image }));
  }, []);

  const goToStage = useCallback((stage: TraceStageId) => {
    setState((s) => {
      // Never allow jumping ahead of what's actually been reached --
      // per spec section 11, the timeline is clickable only when valid.
      if (stage > s.highestReachedStage) return s;
      return { ...s, currentStage: stage };
    });
  }, []);

  const beginRun = useCallback((kind: RunKind) => {
    setState((s) => ({
      ...s,
      currentStage: kind === "discover" ? 2 : s.currentStage,
      highestReachedStage:
        kind === "discover" ? (Math.max(s.highestReachedStage, 2) as TraceStageId) : s.highestReachedStage,
      systemStatus: "active",
      stageEvents: [],
      isRunning: true,
      lastFinalStatus: null,
      runKind: kind,
    }));
  }, []);

  /** Called for every real StageRecord as it streams in from the backend. */
  const recordStage = useCallback((record: StageRecord) => {
    setState((s) => {
      const traceStage = BACKEND_STAGE_TO_TRACE_STAGE[record.stage];
      const next: TraceState = {
        ...s,
        stageEvents: [...s.stageEvents, record],
      };
      if (traceStage) {
        next.currentStage = traceStage;
        next.highestReachedStage = Math.max(
          s.highestReachedStage,
          traceStage,
        ) as TraceStageId;
      }
      if (record.stage === "BLOCKCHAIN_REGISTER" && record.status === "pass") {
        next.systemStatus = "anchoring";
      }
      return next;
    });
  }, []);

  const completeRun = useCallback((result: { final_status: string } & Record<string, unknown>) => {
    setState((s) => {
      const reachedVerify = result.final_status === "on_chain_verified";
      return {
        ...s,
        currentStage: reachedVerify ? 6 : s.currentStage,
        highestReachedStage: reachedVerify
          ? 6
          : (s.highestReachedStage as TraceStageId),
        systemStatus: reachedVerify ? "verified" : "online",
        isRunning: false,
        lastFinalStatus: result.final_status,
        lastResult: result,
        discoveredMatch: (result.match as Record<string, unknown> | undefined) ?? s.discoveredMatch,
      };
    });
  }, []);

  const haltRun = useCallback(() => {
    setState((s) => ({ ...s, systemStatus: "halted", isRunning: false }));
  }, []);

  return { state, setImage, goToStage, beginRun, recordStage, completeRun, haltRun };
}
