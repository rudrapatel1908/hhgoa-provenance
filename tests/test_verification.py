"""
Tests the EVIDENCE_DECISION stage of the pipeline in isolation by mocking
every external dependency (vision, source fetch, search) and running in
dry-run mode so no blockchain/IPFS calls occur. Confirms the gate table
produces CORROBORATED, VERIFIED, or REJECTED for the right reasons.
"""

from unittest.mock import patch, MagicMock
import io

from PIL import Image

from src import pipeline as pipeline_mod
from src.models import (
    FaceComparisonResult, FaceEvidence, SearchCandidate, SearchResult,
    SourceEvidence, StageStatus,
)


def _tiny_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="red").save(buf, format="JPEG")
    return buf.getvalue()


def _usable_face_evidence():
    return FaceEvidence(
        face_count=1, embedding=[0.1] * 128, embedding_sha256="a" * 64, quality_pass=True,
    )


def _make_pipeline_environment(tmp_path, *, rediscovered: bool, face_pass: bool = True):
    image_path = tmp_path / "input.jpg"
    image_path.write_bytes(_tiny_jpeg_bytes())

    source_evidence = SourceEvidence(
        url="https://x.com/user/status/1", canonical_url="https://x.com/user/status/1",
        reachable=True, http_status=200, platform="x.com", title="Post",
        image_url="https://x.com/img.jpg", image_bytes=_tiny_jpeg_bytes(),
        extraction_method="og:image",
    )

    comparison = FaceComparisonResult(
        method="face_recognition.face_distance",
        distance=0.3 if face_pass else 0.9,
        threshold=0.6,
        decision=StageStatus.PASS if face_pass else StageStatus.FAIL,
    )

    candidates = []
    if rediscovered:
        candidates = [SearchCandidate(
            url="https://x.com/user/status/1", canonical_url="https://x.com/user/status/1",
            search_rank=0,
        )]
    search_result = SearchResult(
        provider="serpapi", method="google_lens", candidates=candidates,
        raw_candidate_count=len(candidates), query_image_ref="https://x.com/img.jpg",
    )

    return str(image_path), source_evidence, comparison, search_result


def test_positive_case_corroborated(tmp_path):
    image_path, source_evidence, comparison, search_result = _make_pipeline_environment(
        tmp_path, rediscovered=True,
    )
    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch.object(pipeline_mod.source_mod, "fetch_source", return_value=source_evidence), \
         patch.object(pipeline_mod.vision_mod, "compare_faces", return_value=comparison), \
         patch("src.search.SerpApiGoogleLensProvider.search_by_image_bytes", return_value=search_result):
        config = pipeline_mod.PipelineConfig()
        config.serpapi_key = "fake-key"
        result = pipeline_mod.register(
            image_path=image_path, claimed_url=source_evidence.url,
            config=config, dry_run=True,
        )

    assert result.final_status.value == "corroborated"


def test_negative_case_face_mismatch_rejected(tmp_path):
    image_path, source_evidence, comparison, search_result = _make_pipeline_environment(
        tmp_path, rediscovered=True, face_pass=False,
    )
    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch.object(pipeline_mod.source_mod, "fetch_source", return_value=source_evidence), \
         patch.object(pipeline_mod.vision_mod, "compare_faces", return_value=comparison):
        result = pipeline_mod.register(
            image_path=image_path, claimed_url=source_evidence.url,
            config=pipeline_mod.PipelineConfig(), dry_run=True,
        )

    assert result.final_status.value == "rejected"


def test_insufficient_evidence_no_corroboration_yields_verified_not_corroborated(tmp_path):
    image_path, source_evidence, comparison, search_result = _make_pipeline_environment(
        tmp_path, rediscovered=False,
    )
    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch.object(pipeline_mod.source_mod, "fetch_source", return_value=source_evidence), \
         patch.object(pipeline_mod.vision_mod, "compare_faces", return_value=comparison), \
         patch("src.search.SerpApiGoogleLensProvider.search_by_image_bytes", return_value=search_result):
        config = pipeline_mod.PipelineConfig()
        config.serpapi_key = "fake-key"
        result = pipeline_mod.register(
            image_path=image_path, claimed_url=source_evidence.url,
            config=config, dry_run=True,
        )

    assert result.final_status.value == "verified"


def test_source_unreachable_rejected(tmp_path):
    image_path, source_evidence, comparison, search_result = _make_pipeline_environment(
        tmp_path, rediscovered=True,
    )
    unreachable = SourceEvidence(
        url="https://x.com/dead", canonical_url="https://x.com/dead",
        reachable=False, error="http_error_404",
    )
    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch.object(pipeline_mod.source_mod, "fetch_source", return_value=unreachable):
        result = pipeline_mod.register(
            image_path=image_path, claimed_url="https://x.com/dead",
            config=pipeline_mod.PipelineConfig(), dry_run=True,
        )

    assert result.final_status.value == "rejected"


def test_dry_run_never_touches_blockchain(tmp_path):
    image_path, source_evidence, comparison, search_result = _make_pipeline_environment(
        tmp_path, rediscovered=True,
    )
    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch.object(pipeline_mod.source_mod, "fetch_source", return_value=source_evidence), \
         patch.object(pipeline_mod.vision_mod, "compare_faces", return_value=comparison), \
         patch("src.search.SerpApiGoogleLensProvider.search_by_image_bytes", return_value=search_result), \
         patch.object(pipeline_mod, "ChainConfig") as mock_chain_config:
        config = pipeline_mod.PipelineConfig()
        config.serpapi_key = "fake-key"
        result = pipeline_mod.register(
            image_path=image_path, claimed_url=source_evidence.url,
            config=config, dry_run=True,
        )

    mock_chain_config.from_env.assert_not_called()
    assert result.blockchain is None
    assert result.onchain_verification is None
    assert result.dry_run is True


def test_live_search_uses_original_input_image_not_source_image(tmp_path):
    """Locks in the corroboration-semantics fix: register() must search
    the ORIGINAL INPUT image, not the claimed source's own image. This
    is the actual evidence-quality distinction the fix was about --
    without this test, a regression back to searching the source image
    would pass every other test silently."""
    image_path = tmp_path / "input.jpg"
    distinct_input_bytes = _tiny_jpeg_bytes() + b"INPUT_IMAGE_MARKER"
    image_path.write_bytes(distinct_input_bytes)

    source_evidence = SourceEvidence(
        url="https://x.com/user/status/1", canonical_url="https://x.com/user/status/1",
        reachable=True, http_status=200, platform="x.com", title="Post",
        image_url="https://x.com/img.jpg",
        image_bytes=_tiny_jpeg_bytes() + b"SOURCE_IMAGE_MARKER",  # deliberately different bytes
        extraction_method="og:image",
    )
    comparison = FaceComparisonResult(
        method="face_recognition.face_distance", distance=0.2, threshold=0.6, decision=StageStatus.PASS,
    )
    search_result = SearchResult(
        provider="serpapi", method="google_lens", candidates=[],
        raw_candidate_count=0, query_image_ref="uploaded:test",
    )

    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch.object(pipeline_mod.source_mod, "fetch_source", return_value=source_evidence), \
         patch.object(pipeline_mod.vision_mod, "compare_faces", return_value=comparison), \
         patch(
             "src.search.SerpApiGoogleLensProvider.search_by_image_bytes",
             return_value=search_result,
         ) as mock_search:
        config = pipeline_mod.PipelineConfig()
        config.serpapi_key = "fake-key"
        pipeline_mod.register(
            image_path=str(image_path), claimed_url=source_evidence.url,
            config=config, dry_run=True,
        )

    assert mock_search.called
    called_bytes = mock_search.call_args[0][0]  # first positional arg
    assert called_bytes == distinct_input_bytes, (
        "register() must search the original input image bytes, not the "
        "claimed source's own image bytes"
    )
