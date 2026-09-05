// Mirrors src/models.py. Keep field names identical to the backend's
// JSON output -- do not rename on this side, so a mismatch is
// immediately visible as a TypeScript error rather than silently
// reading `undefined`.

export type StageStatus = "pass" | "fail" | "skipped";

export interface StageRecord {
  stage: string; // backend's internal stage name, e.g. "FACE_ANALYSIS"
  status: StageStatus;
  duration_ms: number;
  detail: string;
  error: string | null;
}

export type EvidenceStatus =
  | "rejected"
  | "no_match"
  | "discovered"
  | "verified"
  | "corroborated"
  | "on_chain_verified";

export interface PipelineResult {
  final_status: EvidenceStatus;
  stages: StageRecord[];
  manifest?: Record<string, unknown> | null;
  manifest_hash_hex?: string | null;
  ipfs_cid?: string | null;
  blockchain?: {
    tx_hash: string;
    block_number: number;
  } | null;
  onchain_verification?: {
    hashes_match: boolean;
    onchain_submitter?: string;
    onchain_timestamp?: number;
  } | null;
  dry_run: boolean;
}

export interface DiscoveryResult {
  final_status: EvidenceStatus;
  stages: StageRecord[];
  raw_candidate_count?: number;
  visual_match_count?: number;
  exact_match_count?: number;
  social_candidate_count?: number;
  match?: {
    candidate: { url: string; canonical_url: string };
    platform: string;
    face_comparison: { distance: number; threshold: number };
    candidate_rank: number;
  } | null;
}

export interface AuditResult {
  local_hash: string;
  registered_hash: string | null;
  onchain_exists: boolean;
  onchain_submitter?: string;
  onchain_timestamp?: number;
  status:
    | "NOT_REGISTERED"
    | "ON_CHAIN_VERIFIED"
    | "TAMPER_DETECTED"
    | "REGISTERED_HASH_NOT_FOUND_ON_CHAIN";
}

// -----------------------------------------------------------------
// The backend's internal stage names are more granular than TRACE's
// six user-facing stages. This table is the SINGLE source of truth
// for that mapping -- every component that groups stage events by
// TRACE-stage must import this, not hardcode its own list.
// -----------------------------------------------------------------
export type TraceStageId = 1 | 2 | 3 | 4 | 5 | 6;

export const TRACE_STAGE_LABELS: Record<TraceStageId, string> = {
  1: "LOCK",
  2: "FACE",
  3: "SEARCH",
  4: "SOURCE",
  5: "ANCHOR",
  6: "VERIFY",
};

export const BACKEND_STAGE_TO_TRACE_STAGE: Record<string, TraceStageId> = {
  INPUT_VALIDATION: 1,
  FACE_ANALYSIS: 2,
  SOURCE_FETCH: 4,
  FACE_COMPARISON: 4,
  LIVE_SEARCH: 3,
  CANDIDATE_VALIDATION: 3,
  CANDIDATE_PROCESSING: 3,
  SOCIAL_SOURCE_VALIDATION: 4,
  FACE_CORRESPONDENCE: 4,
  EVIDENCE_DECISION: 4,
  MANIFEST_BUILD: 5,
  IPFS_PIN: 5,
  BLOCKCHAIN_REGISTER: 5,
  WAIT_FOR_CONFIRMATION: 5,
  ON_CHAIN_VERIFY: 6,
};
