"""
Pipeline orchestration. Contains NO provider-specific logic -- it calls
into vision.py / source.py / search.py / manifest.py / ipfs.py /
blockchain.py and enforces the fail-closed state machine described in
the README's "Threat model" and "Failure states" sections.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from pathlib import Path
from typing import Optional

from PIL import Image
import io

from . import manifest as manifest_mod
from . import source as source_mod
from . import search as search_mod
from . import vision as vision_mod
from . import ipfs as ipfs_mod
from .blockchain import ChainConfig, RegistryClient, ConfigError, TransactionFailed
from .models import (
    EvidenceGate, EvidenceStatus, ManifestClaimedSource, ManifestFace,
    ManifestInput, ManifestRecord, ManifestSearch, ManifestVerification,
    PipelineResult, StageRecord, StageStatus, VerificationPolicy,
    VerificationResult,
)

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA = "hhgoa.media-provenance"
MANIFEST_SCHEMA_VERSION = 1

# Self-describing policy record embedded in every manifest -- bump the
# version string whenever the rules below actually change, so old
# manifests remain honestly labeled with the rules that produced them.
VERIFICATION_POLICY = VerificationPolicy(
    version="1.1",
    single_face_required=True,
    source_access_required=True,
    face_match_required=True,
    live_search_required=False,  # search may be SKIPPED without forcing REJECTED
    source_rediscovery_required_for_corroboration=True,
)


class PipelineConfig:
    def __init__(self):
        self.face_distance_threshold = float(os.environ.get("FACE_DISTANCE_THRESHOLD", "0.6"))
        self.max_search_results = int(os.environ.get("MAX_SEARCH_RESULTS", "20"))
        self.serpapi_key = os.environ.get("SERPAPI_API_KEY")
        self.pinata_jwt = os.environ.get("PINATA_JWT")


def _timed(fn, *args, **kwargs):
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    duration_ms = (time.perf_counter() - start) * 1000
    return result, duration_ms


def _image_dimensions(image_bytes: bytes) -> tuple[int, int, str]:
    with Image.open(io.BytesIO(image_bytes)) as img:
        return img.width, img.height, (img.format or "unknown").lower()


def register(
    *,
    image_path: str,
    claimed_url: str,
    config: Optional[PipelineConfig] = None,
    dry_run: bool = False,
) -> PipelineResult:
    """
    Run the full pipeline:
      INPUT_VALIDATION -> FACE_ANALYSIS -> SOURCE_FETCH -> FACE_COMPARISON
      -> LIVE_SEARCH -> CANDIDATE_VALIDATION -> EVIDENCE_DECISION
      -> MANIFEST_BUILD -> MANIFEST_HASH -> IPFS_PIN -> BLOCKCHAIN_REGISTER
      -> WAIT_FOR_CONFIRMATION -> ON_CHAIN_VERIFY -> PROOF_BUNDLE

    Returns a PipelineResult whose final_status is the HIGHEST evidence
    state actually earned. Never returns ON_CHAIN_VERIFIED unless a
    confirmed transaction and an independent read-only check both pass.
    """
    config = config or PipelineConfig()
    stages: list[StageRecord] = []

    def stage_fail(name: str, detail: str, status: EvidenceStatus) -> PipelineResult:
        stages.append(StageRecord(stage=name, status=StageStatus.FAIL, duration_ms=0, error=detail))
        return PipelineResult(final_status=status, stages=stages, dry_run=dry_run)

    # ---- INPUT_VALIDATION -------------------------------------------------
    t0 = time.perf_counter()
    try:
        with open(image_path, "rb") as f:
            original_bytes = f.read()
    except OSError as exc:
        return stage_fail("INPUT_VALIDATION", f"cannot read image file: {exc}", EvidenceStatus.REJECTED)

    if not original_bytes:
        return stage_fail("INPUT_VALIDATION", "image file is empty", EvidenceStatus.REJECTED)

    original_sha256 = hashlib.sha256(original_bytes).hexdigest()
    try:
        width, height, fmt = _image_dimensions(original_bytes)
    except Exception as exc:
        return stage_fail("INPUT_VALIDATION", f"unreadable image: {exc}", EvidenceStatus.REJECTED)

    stages.append(StageRecord(
        stage="INPUT_VALIDATION", status=StageStatus.PASS,
        duration_ms=(time.perf_counter() - t0) * 1000,
        detail=f"sha256={original_sha256} {width}x{height} {fmt}",
    ))

    # ---- FACE_ANALYSIS ------------------------------------------------
    face_evidence, dur = _timed(vision_mod.analyze_face, original_bytes)
    if not face_evidence.usable:
        stages.append(StageRecord(
            stage="FACE_ANALYSIS", status=StageStatus.FAIL, duration_ms=dur,
            error=face_evidence.error, detail="; ".join(face_evidence.quality_notes),
        ))
        return PipelineResult(final_status=EvidenceStatus.REJECTED, stages=stages, dry_run=dry_run)
    stages.append(StageRecord(
        stage="FACE_ANALYSIS", status=StageStatus.PASS, duration_ms=dur,
        detail=f"faces={face_evidence.face_count}",
    ))

    # ---- SOURCE_FETCH ---------------------------------------------------
    source_evidence, dur = _timed(source_mod.fetch_source, claimed_url)
    if not source_evidence.reachable or not source_evidence.image_bytes:
        stages.append(StageRecord(
            stage="SOURCE_FETCH", status=StageStatus.FAIL, duration_ms=dur,
            error=source_evidence.error,
        ))
        return PipelineResult(final_status=EvidenceStatus.REJECTED, stages=stages, dry_run=dry_run)
    stages.append(StageRecord(
        stage="SOURCE_FETCH", status=StageStatus.PASS, duration_ms=dur,
        detail=f"platform={source_evidence.platform} method={source_evidence.extraction_method}",
    ))

    # ---- FACE_COMPARISON --------------------------------------------------
    source_face, dur1 = _timed(vision_mod.analyze_face, source_evidence.image_bytes)
    if not source_face.usable:
        stages.append(StageRecord(
            stage="FACE_COMPARISON", status=StageStatus.FAIL, duration_ms=dur1,
            error=f"source image face analysis failed: {source_face.error}",
        ))
        return PipelineResult(final_status=EvidenceStatus.REJECTED, stages=stages, dry_run=dry_run)

    comparison, dur2 = _timed(
        vision_mod.compare_faces, face_evidence.embedding, source_face.embedding,
        threshold=config.face_distance_threshold,
    )
    stages.append(StageRecord(
        stage="FACE_COMPARISON", status=comparison.decision, duration_ms=dur1 + dur2,
        detail=f"distance={comparison.distance:.4f} threshold={comparison.threshold}",
    ))
    if comparison.decision != StageStatus.PASS:
        return PipelineResult(final_status=EvidenceStatus.REJECTED, stages=stages, dry_run=dry_run)

    # ---- LIVE_SEARCH -------------------------------------------------------
    # Searches the ORIGINAL INPUT IMAGE (uploaded via the same mechanism
    # discover() uses), not the claimed source's own image. This matters:
    # searching the source's image only proves the source itself is
    # independently indexed, whereas searching the original input proves
    # something stronger and more directly relevant -- that starting from
    # nothing but the input photo, live search independently arrives at
    # this exact claimed URL. That is the literal Task 3 requirement
    # (face scan -> web search -> matching post), and it's the same
    # standard discover() already meets. (Audited and switched from the
    # previous source-image-based search for this reason.)
    search_result = None
    candidates = []
    fmt_for_upload = "jpeg" if fmt == "jpg" else fmt
    if config.serpapi_key:
        provider = search_mod.SerpApiGoogleLensProvider(config.serpapi_key)
        search_result, dur = _timed(
            provider.search_by_image_bytes, original_bytes,
            image_format=fmt_for_upload, max_results=config.max_search_results,
        )
        if search_result.succeeded:
            candidates = search_mod.dedupe_candidates(search_result.candidates)
            stages.append(StageRecord(
                stage="LIVE_SEARCH", status=StageStatus.PASS, duration_ms=dur,
                detail=(
                    f"visual_matches={search_result.visual_match_count} "
                    f"exact_matches={search_result.exact_match_count} "
                    f"raw={search_result.raw_candidate_count}"
                ),
            ))
        else:
            stages.append(StageRecord(
                stage="LIVE_SEARCH", status=StageStatus.FAIL, duration_ms=dur,
                error=search_result.error,
            ))
    else:
        stages.append(StageRecord(
            stage="LIVE_SEARCH", status=StageStatus.SKIPPED, duration_ms=0,
            detail="SERPAPI_API_KEY not configured",
        ))

    # ---- CANDIDATE_VALIDATION / EVIDENCE_DECISION -----------------------------
    t0 = time.perf_counter()
    gates = [
        EvidenceGate("source_accessible", StageStatus.PASS, source_evidence.canonical_url),
        EvidenceGate("source_image_extracted", StageStatus.PASS, source_evidence.extraction_method or ""),
        EvidenceGate("face_correspondence", comparison.decision,
                     f"distance={comparison.distance:.4f}"),
    ]

    rediscovered_candidate = None
    if candidates:
        rediscovered_candidate = search_mod.find_matching_candidate(
            candidates, source_evidence.canonical_url
        )
        gates.append(EvidenceGate(
            "claimed_url_rediscovered",
            StageStatus.PASS if rediscovered_candidate else StageStatus.FAIL,
            f"{len(candidates)} candidates evaluated",
        ))
    else:
        gates.append(EvidenceGate("claimed_url_rediscovered", StageStatus.SKIPPED, "search unavailable"))

    if rediscovered_candidate is not None:
        evidence_status = EvidenceStatus.CORROBORATED
    else:
        evidence_status = EvidenceStatus.VERIFIED  # claimed source + face pass, no search corroboration

    verification = VerificationResult(
        status=evidence_status, gates=gates, face_comparison=comparison,
        claimed_source_rediscovered=rediscovered_candidate is not None,
        rediscovered_candidate=rediscovered_candidate,
        reason="all direct-evidence gates passed" if evidence_status == EvidenceStatus.CORROBORATED
               else "direct evidence passed; independent search corroboration not established",
    )
    decision_detail = (
        "STATUS: CORROBORATED (source independently rediscovered by live search)"
        if evidence_status == EvidenceStatus.CORROBORATED
        else "STATUS: VERIFIED / CORROBORATION: NOT ESTABLISHED"
    )
    stages.append(StageRecord(
        stage="EVIDENCE_DECISION", status=StageStatus.PASS,
        duration_ms=(time.perf_counter() - t0) * 1000, detail=decision_detail,
    ))

    # ---- MANIFEST_BUILD / MANIFEST_HASH ------------------------------------
    t0 = time.perf_counter()
    record = ManifestRecord(
        schema=MANIFEST_SCHEMA,
        schema_version=MANIFEST_SCHEMA_VERSION,
        record_id=str(uuid.uuid4()),
        created_at=ManifestRecord.new_created_at(),
        input=ManifestInput(
            sha256=original_sha256, mime_type=f"image/{fmt}",
            width=width, height=height, file_size_bytes=len(original_bytes),
        ),
        face=ManifestFace(
            count=face_evidence.face_count,
            embedding_sha256=face_evidence.embedding_sha256,
            quality="pass",
            match_method=comparison.method,
            match_distance=round(comparison.distance, 6),
            match_threshold=comparison.threshold,
            match_decision=comparison.decision.value,
        ),
        claimed_source=ManifestClaimedSource(
            url=source_evidence.url, canonical_url=source_evidence.canonical_url,
            platform=source_evidence.platform or "unknown", title=source_evidence.title or "",
        ),
        search=ManifestSearch(
            provider="serpapi" if search_result else "unavailable",
            method="google_lens" if search_result else "none",
            query_source="original_input_image",
            candidate_count=len(candidates),
            exact_match_count=search_result.exact_match_count if search_result else 0,
            visual_match_count=search_result.visual_match_count if search_result else 0,
            claimed_source_rediscovered=verification.claimed_source_rediscovered,
        ),
        verification=ManifestVerification(
            status=verification.status.value, method="face_and_source_and_search",
            policy=VERIFICATION_POLICY,
        ),
    )
    manifest_hash_hex = manifest_mod.manifest_sha256_hex(record)
    stages.append(StageRecord(
        stage="MANIFEST_BUILD", status=StageStatus.PASS,
        duration_ms=(time.perf_counter() - t0) * 1000, detail=manifest_hash_hex,
    ))

    result = PipelineResult(
        final_status=verification.status, stages=stages, manifest=record,
        manifest_hash_hex=manifest_hash_hex, dry_run=dry_run,
    )

    if dry_run:
        stages.append(StageRecord(
            stage="BLOCKCHAIN_REGISTER", status=StageStatus.SKIPPED, duration_ms=0,
            detail="dry-run: no transaction sent, no on-chain verification claimed",
        ))
        return result

    # ---- IPFS_PIN ------------------------------------------------------------
    import dataclasses
    manifest_dict = dataclasses.asdict(record)
    t0 = time.perf_counter()
    pin_result = ipfs_mod.pin_manifest(manifest_dict, jwt=config.pinata_jwt)
    if pin_result.pinned:
        result.ipfs_cid = pin_result.cid
        stages.append(StageRecord(
            stage="IPFS_PIN", status=StageStatus.PASS,
            duration_ms=(time.perf_counter() - t0) * 1000, detail=pin_result.cid,
        ))
    else:
        # IPFS is not a single point of failure for chain registration --
        # continue with an empty manifestURI, per project policy.
        stages.append(StageRecord(
            stage="IPFS_PIN", status=StageStatus.SKIPPED,
            duration_ms=(time.perf_counter() - t0) * 1000, error=pin_result.error,
        ))

    # ---- BLOCKCHAIN_REGISTER / WAIT_FOR_CONFIRMATION / ON_CHAIN_VERIFY -----
    try:
        chain_config = ChainConfig.from_env()
        client = RegistryClient(chain_config)
    except ConfigError as exc:
        stages.append(StageRecord(
            stage="BLOCKCHAIN_REGISTER", status=StageStatus.FAIL, duration_ms=0, error=str(exc),
        ))
        return result  # still returns CORROBORATED/VERIFIED -- just not on-chain

    record_hash_bytes = bytes.fromhex(manifest_hash_hex[2:])
    manifest_uri = f"ipfs://{result.ipfs_cid}" if result.ipfs_cid else ""

    t0 = time.perf_counter()
    try:
        registration = client.register_record(record_hash_bytes, manifest_uri)
    except TransactionFailed as exc:
        stages.append(StageRecord(
            stage="BLOCKCHAIN_REGISTER", status=StageStatus.FAIL,
            duration_ms=(time.perf_counter() - t0) * 1000, error=str(exc),
        ))
        return result

    result.blockchain = registration
    stages.append(StageRecord(
        stage="BLOCKCHAIN_REGISTER", status=StageStatus.PASS,
        duration_ms=(time.perf_counter() - t0) * 1000,
        detail=f"tx={registration.tx_hash} block={registration.block_number}",
    ))

    t0 = time.perf_counter()
    onchain_verification = client.verify_record(record_hash_bytes, manifest_hash_hex)
    result.onchain_verification = onchain_verification
    if onchain_verification.hashes_match:
        stages.append(StageRecord(
            stage="ON_CHAIN_VERIFY", status=StageStatus.PASS,
            duration_ms=(time.perf_counter() - t0) * 1000,
            detail="local digest == on-chain digest",
        ))
        result.final_status = EvidenceStatus.ON_CHAIN_VERIFIED
    else:
        stages.append(StageRecord(
            stage="ON_CHAIN_VERIFY", status=StageStatus.FAIL,
            duration_ms=(time.perf_counter() - t0) * 1000,
            error="on-chain digest did not match local digest",
        ))

    return result


MAX_DISCOVERY_CANDIDATES_VALIDATED = 5  # cap network calls when validating candidates


def discover(
    *,
    image_path: str,
    config: Optional[PipelineConfig] = None,
) -> "DiscoveryResult":
    """
    Image-only discovery: the primary Task 3 flow. Never sends a
    blockchain transaction -- entirely off-chain.

      INPUT_VALIDATION -> FACE_ANALYSIS -> LIVE_SEARCH (image upload)
      -> CANDIDATE_PROCESSING -> SOCIAL_FILTERING -> SOURCE_VALIDATION
      -> FACE_CORRESPONDENCE -> best matching social-media post

    Candidates are validated in search-rank order (already the
    provider's relevance ranking); the first social candidate whose
    source can be fetched AND whose face matches is returned. This is
    NOT `results[0]` -- unreachable pages, pages with no extractable
    image, and face mismatches are all skipped in favor of the next
    candidate, and none of that is decided in advance.
    """
    from .models import DiscoveredMatch, DiscoveryResult

    config = config or PipelineConfig()
    stages: list[StageRecord] = []

    def fail(name: str, detail: str, status: EvidenceStatus) -> "DiscoveryResult":
        stages.append(StageRecord(stage=name, status=StageStatus.FAIL, duration_ms=0, error=detail))
        return DiscoveryResult(final_status=status, stages=stages)

    # ---- INPUT_VALIDATION -------------------------------------------------
    t0 = time.perf_counter()
    try:
        with open(image_path, "rb") as f:
            original_bytes = f.read()
    except OSError as exc:
        return fail("INPUT_VALIDATION", f"cannot read image file: {exc}", EvidenceStatus.REJECTED)
    if not original_bytes:
        return fail("INPUT_VALIDATION", "image file is empty", EvidenceStatus.REJECTED)

    original_sha256 = hashlib.sha256(original_bytes).hexdigest()
    try:
        width, height, fmt = _image_dimensions(original_bytes)
    except Exception as exc:
        return fail("INPUT_VALIDATION", f"unreadable image: {exc}", EvidenceStatus.REJECTED)
    stages.append(StageRecord(
        stage="INPUT_VALIDATION", status=StageStatus.PASS,
        duration_ms=(time.perf_counter() - t0) * 1000,
        detail=f"sha256={original_sha256} {width}x{height} {fmt}",
    ))

    # Fail fast on missing config before doing any face-detection work.
    if not config.serpapi_key:
        return fail("LIVE_SEARCH", "SERPAPI_API_KEY not configured", EvidenceStatus.REJECTED)

    # ---- FACE_ANALYSIS ------------------------------------------------
    face_evidence, dur = _timed(vision_mod.analyze_face, original_bytes)
    if not face_evidence.usable:
        stages.append(StageRecord(
            stage="FACE_ANALYSIS", status=StageStatus.FAIL, duration_ms=dur,
            error=face_evidence.error,
        ))
        return DiscoveryResult(final_status=EvidenceStatus.REJECTED, stages=stages)
    stages.append(StageRecord(
        stage="FACE_ANALYSIS", status=StageStatus.PASS, duration_ms=dur,
        detail=f"faces={face_evidence.face_count}",
    ))

    # ---- LIVE_SEARCH (image-only, via the real SerpApi upload endpoint) ---

    fmt_for_upload = "jpeg" if fmt == "jpg" else fmt
    provider = search_mod.SerpApiGoogleLensProvider(config.serpapi_key)
    search_result, dur = _timed(
        provider.search_by_image_bytes, original_bytes,
        image_format=fmt_for_upload, max_results=config.max_search_results,
    )
    if not search_result.succeeded:
        stages.append(StageRecord(
            stage="LIVE_SEARCH", status=StageStatus.FAIL, duration_ms=dur,
            error=search_result.error,
        ))
        return DiscoveryResult(final_status=EvidenceStatus.REJECTED, stages=stages)
    stages.append(StageRecord(
        stage="LIVE_SEARCH", status=StageStatus.PASS, duration_ms=dur,
        detail=(
            f"visual_matches={search_result.visual_match_count} "
            f"exact_matches={search_result.exact_match_count} "
            f"raw={search_result.raw_candidate_count}"
        ),
    ))

    # ---- CANDIDATE_PROCESSING / SOCIAL_FILTERING ---------------------------
    t0 = time.perf_counter()
    deduped = search_mod.dedupe_candidates(search_result.candidates)
    social_candidates = [c for c in deduped if source_mod.is_social_platform(c.canonical_url)]
    stages.append(StageRecord(
        stage="CANDIDATE_PROCESSING", status=StageStatus.PASS,
        duration_ms=(time.perf_counter() - t0) * 1000,
        detail=f"candidates={len(deduped)} social_candidates={len(social_candidates)}",
    ))
    if not social_candidates:
        stages.append(StageRecord(
            stage="SOCIAL_SOURCE_VALIDATION", status=StageStatus.SKIPPED, duration_ms=0,
            detail="no social-media candidates in search results",
        ))
        return DiscoveryResult(
            final_status=EvidenceStatus.NO_MATCH, stages=stages,
            raw_candidate_count=search_result.raw_candidate_count,
            visual_match_count=search_result.visual_match_count,
            exact_match_count=search_result.exact_match_count,
            social_candidate_count=0,
        )

    # ---- SOURCE_VALIDATION / FACE_CORRESPONDENCE ---------------------------
    # Try social candidates in their existing rank order, skipping any that
    # fail to fetch, yield no usable face, or don't match -- never assuming
    # the first one is correct.
    t0 = time.perf_counter()
    best_match = None
    for candidate in social_candidates[:MAX_DISCOVERY_CANDIDATES_VALIDATED]:
        evidence = source_mod.fetch_source(candidate.url)
        if not evidence.reachable or not evidence.image_bytes:
            continue
        candidate_face = vision_mod.analyze_face(evidence.image_bytes)
        if not candidate_face.usable:
            continue
        comparison = vision_mod.compare_faces(
            face_evidence.embedding, candidate_face.embedding,
            threshold=config.face_distance_threshold,
        )
        if comparison.decision == StageStatus.PASS:
            best_match = DiscoveredMatch(
                candidate=candidate, platform=source_mod.classify_platform(candidate.canonical_url),
                face_comparison=comparison, candidate_rank=candidate.search_rank or 0,
            )
            break

    duration_ms = (time.perf_counter() - t0) * 1000
    if best_match is None:
        stages.append(StageRecord(
            stage="SOCIAL_SOURCE_VALIDATION", status=StageStatus.FAIL, duration_ms=duration_ms,
            error=f"no social candidate (of {len(social_candidates)} checked) passed source access + face match",
        ))
        return DiscoveryResult(
            final_status=EvidenceStatus.NO_MATCH, stages=stages,
            raw_candidate_count=search_result.raw_candidate_count,
            visual_match_count=search_result.visual_match_count,
            exact_match_count=search_result.exact_match_count,
            social_candidate_count=len(social_candidates),
        )

    stages.append(StageRecord(
        stage="SOCIAL_SOURCE_VALIDATION", status=StageStatus.PASS, duration_ms=duration_ms,
        detail=f"platform={best_match.platform} rank=#{best_match.candidate_rank + 1}",
    ))
    stages.append(StageRecord(
        stage="FACE_CORRESPONDENCE", status=StageStatus.PASS, duration_ms=0,
        detail=f"distance={best_match.face_comparison.distance:.4f} threshold={best_match.face_comparison.threshold}",
    ))

    return DiscoveryResult(
        final_status=EvidenceStatus.DISCOVERED, stages=stages,
        raw_candidate_count=search_result.raw_candidate_count,
        visual_match_count=search_result.visual_match_count,
        exact_match_count=search_result.exact_match_count,
        social_candidate_count=len(social_candidates),
        match=best_match,
    )


def check_config() -> dict:
    """
    Read-only pre-flight check: confirms RPC connects, wallet derives,
    ABI loads, and the configured contract address is reachable. Never
    sends a transaction. Shared by both the CLI and the API adapter so
    they can never drift from each other.
    """
    from .blockchain import ChainConfig, ConfigError, RegistryClient

    try:
        chain_config = ChainConfig.from_env()
        client = RegistryClient(chain_config)  # __init__ already checks RPC connectivity
        # Read-only call against an address that should never exist,
        # purely to prove the ABI + contract address round-trip works.
        client.verify_record(b"\x00" * 32, "0x" + "00" * 32)
    except ConfigError as exc:
        return {"ok": False, "error": f"configuration_error: {exc}"}
    except Exception as exc:  # noqa: BLE001 - surface any ABI/contract mismatch plainly
        return {"ok": False, "error": f"contract_or_abi_check_failed: {exc}"}

    return {
        "ok": True,
        "rpc_url": chain_config.rpc_url,
        "wallet": client.address,
        "contract_address": chain_config.contract_address,
        "chain_id": chain_config.chain_id,
    }


def audit(manifest_path: str, verification_path: str = None) -> dict:
    """
    Re-hash a manifest.json from disk using the exact same canonicalization
    code path as registration, then independently query the chain --
    correctly, this time.

    IMPORTANT DESIGN NOTE (fixed after a real bug found during final
    pre-transaction validation): the contract stores records in a mapping
    keyed by hash. If we simply re-hash a *tampered* manifest and look up
    THAT hash on-chain, the lookup returns "not found" -- because a
    tampered manifest hashes to a value that was never registered under
    that key. That is NOT the same as "found, but mismatched", and it
    would have made the tamper demo silently report the wrong status
    (NOT_FOUND_ON_CHAIN instead of TAMPER_DETECTED).

    The correct approach: read the ORIGINALLY REGISTERED hash from the
    sibling `verification.json` written at registration time, query the
    chain using THAT hash (confirming it's genuinely registered), and
    compare it against the hash of the manifest as it exists on disk
    right now. A mismatch between those two is what tampering actually
    looks like.
    """
    import json as json_mod

    manifest_dir = Path(manifest_path).parent
    if verification_path is None:
        verification_path = str(manifest_dir / "verification.json")

    with open(manifest_path) as f:
        manifest_dict = json_mod.load(f)
    current_local_hash = manifest_mod.dict_sha256_hex(manifest_dict)

    if not Path(verification_path).exists():
        # No registration has ever happened for this manifest -- there is
        # nothing to compare against, and no chain call is warranted.
        return {
            "local_hash": current_local_hash,
            "registered_hash": None,
            "onchain_exists": False,
            "status": "NOT_REGISTERED",
        }

    with open(verification_path) as f:
        verification_dict = json_mod.load(f)

    registered_hash = verification_dict.get("local_manifest_hash")
    if verification_dict.get("dry_run") or not registered_hash:
        return {
            "local_hash": current_local_hash,
            "registered_hash": registered_hash,
            "onchain_exists": False,
            "status": "NOT_REGISTERED",
        }

    chain_config = ChainConfig.from_env()
    client = RegistryClient(chain_config)
    registered_hash_bytes = bytes.fromhex(registered_hash[2:])
    onchain = client.verify_record(registered_hash_bytes, registered_hash)

    if not onchain.record_exists:
        # Should not normally happen if registration truly succeeded --
        # surfaced explicitly rather than silently treated as tamper.
        status = "REGISTERED_HASH_NOT_FOUND_ON_CHAIN"
    elif current_local_hash.lower() == registered_hash.lower():
        status = "ON_CHAIN_VERIFIED"
    else:
        status = "TAMPER_DETECTED"

    return {
        "local_hash": current_local_hash,
        "registered_hash": registered_hash,
        "onchain_exists": onchain.record_exists,
        "onchain_submitter": onchain.onchain_submitter,
        "onchain_timestamp": onchain.onchain_timestamp,
        "status": status,
    }
