"""
Typed internal data structures for the media-provenance pipeline.

Every cross-module boundary in this project passes one of these types,
never a bare dict. This is deliberate: dictionary-key typos are the
single most common source of silent bugs in pipelines like this one,
and a typo that silently produces `None` for a "face match distance"
is exactly the kind of thing that could turn into a false VERIFIED.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


# --------------------------------------------------------------------------
# Evidence / verification status
# --------------------------------------------------------------------------

class EvidenceStatus(str, enum.Enum):
    """
    Ordered evidence states. Higher in this list = stronger evidence.
    The pipeline is only ever allowed to *report* the highest state it
    has actually earned -- never assumed, never inferred.
    """
    REJECTED = "rejected"
    NO_MATCH = "no_match"          # discovery ran; no social candidate validated
    DISCOVERED = "discovered"      # a social candidate was found but not yet fully validated
    CLAIMED = "claimed"
    VERIFIED = "verified"
    CORROBORATED = "corroborated"
    ON_CHAIN_VERIFIED = "on_chain_verified"
    TAMPER_DETECTED = "tamper_detected"  # audit-mode only, never from register


class StageStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


# --------------------------------------------------------------------------
# Face analysis
# --------------------------------------------------------------------------

@dataclass
class FaceEvidence:
    """Result of running the vision pipeline on ONE image."""
    face_count: int
    embedding: Optional[list] = None          # raw 128-d vector, in-memory only
    embedding_sha256: Optional[str] = None     # what's allowed into the manifest
    quality_pass: bool = False
    quality_notes: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def usable(self) -> bool:
        return self.face_count == 1 and self.quality_pass and self.embedding is not None


@dataclass
class FaceComparisonResult:
    method: str                 # e.g. "face_recognition.face_distance"
    distance: float
    threshold: float
    decision: StageStatus


# --------------------------------------------------------------------------
# Source (claimed URL) evidence
# --------------------------------------------------------------------------

@dataclass
class SourceEvidence:
    url: str
    canonical_url: str
    reachable: bool
    http_status: Optional[int] = None
    content_type: Optional[str] = None
    platform: Optional[str] = None
    title: Optional[str] = None
    image_url: Optional[str] = None
    image_bytes: Optional[bytes] = None
    extraction_method: Optional[str] = None    # "og:image" | "twitter:image" | "img_tag"
    error: Optional[str] = None


# --------------------------------------------------------------------------
# Search candidates
# --------------------------------------------------------------------------

@dataclass
class SearchCandidate:
    url: str
    canonical_url: str
    title: Optional[str] = None
    source_domain: Optional[str] = None
    thumbnail: Optional[str] = None
    image_url: Optional[str] = None
    search_rank: Optional[int] = None
    is_exact_match: bool = False   # SerpApi's per-candidate "exact_matches" flag
    raw_metadata: dict = field(default_factory=dict)


@dataclass
class SearchResult:
    provider: str
    method: str
    candidates: list[SearchCandidate]
    raw_candidate_count: int
    query_image_ref: str        # opaque description, never the raw bytes
    exact_match_count: int = 0
    visual_match_count: int = 0
    error: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.error is None


# --------------------------------------------------------------------------
# Evidence decision (gate table)
# --------------------------------------------------------------------------

@dataclass
class EvidenceGate:
    name: str
    status: StageStatus
    detail: str = ""


@dataclass
class VerificationResult:
    status: EvidenceStatus
    gates: list[EvidenceGate]
    face_comparison: Optional[FaceComparisonResult] = None
    claimed_source_rediscovered: bool = False
    rediscovered_candidate: Optional[SearchCandidate] = None
    reason: str = ""


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

@dataclass
class ManifestInput:
    sha256: str
    mime_type: str
    width: int
    height: int
    file_size_bytes: int


@dataclass
class ManifestFace:
    count: int
    embedding_sha256: str
    quality: str
    match_method: str
    match_distance: float
    match_threshold: float
    match_decision: str


@dataclass
class ManifestClaimedSource:
    url: str
    canonical_url: str
    platform: str
    title: str


@dataclass
class ManifestSearch:
    provider: str
    method: str
    query_source: str  # "original_input_image" -- what was actually searched
    candidate_count: int
    exact_match_count: int
    visual_match_count: int
    claimed_source_rediscovered: bool


@dataclass
class VerificationPolicy:
    """Self-describing record of the rules applied to reach this
    manifest's verification status -- lets an auditor or judge see
    exactly what was required without reading source code."""
    version: str
    single_face_required: bool
    source_access_required: bool
    face_match_required: bool
    live_search_required: bool
    source_rediscovery_required_for_corroboration: bool


@dataclass
class ManifestVerification:
    status: str
    method: str
    policy: VerificationPolicy


@dataclass
class ManifestRecord:
    schema: str
    schema_version: int
    record_id: str
    created_at: str
    input: ManifestInput
    face: ManifestFace
    claimed_source: ManifestClaimedSource
    search: ManifestSearch
    verification: ManifestVerification

    @staticmethod
    def new_created_at() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Blockchain
# --------------------------------------------------------------------------

@dataclass
class BlockchainRegistration:
    tx_hash: str
    block_number: int
    contract_address: str
    submitter: str
    receipt_status: int


@dataclass
class OnChainVerification:
    record_exists: bool
    onchain_hash_hex: str
    local_hash_hex: str
    hashes_match: bool
    onchain_submitter: Optional[str] = None
    onchain_timestamp: Optional[int] = None


# --------------------------------------------------------------------------
# Pipeline result (top-level)
# --------------------------------------------------------------------------

@dataclass
class StageRecord:
    stage: str
    status: StageStatus
    duration_ms: float
    detail: str = ""
    error: Optional[str] = None


@dataclass
class PipelineResult:
    final_status: EvidenceStatus
    stages: list[StageRecord]
    manifest: Optional[ManifestRecord] = None
    manifest_hash_hex: Optional[str] = None
    ipfs_cid: Optional[str] = None
    blockchain: Optional[BlockchainRegistration] = None
    onchain_verification: Optional[OnChainVerification] = None
    dry_run: bool = False


# --------------------------------------------------------------------------
# Discovery (image-only, primary Task 3 flow)
# --------------------------------------------------------------------------

@dataclass
class DiscoveredMatch:
    """The best validated social-media candidate found by discover()."""
    candidate: SearchCandidate
    platform: str
    face_comparison: FaceComparisonResult
    candidate_rank: int  # position within the search's candidate list, 0-based


@dataclass
class DiscoveryResult:
    final_status: EvidenceStatus  # DISCOVERED, NO_MATCH, or REJECTED
    stages: list[StageRecord]
    raw_candidate_count: int = 0
    visual_match_count: int = 0
    exact_match_count: int = 0
    social_candidate_count: int = 0
    match: Optional[DiscoveredMatch] = None
