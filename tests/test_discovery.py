"""
Tests pipeline.discover() -- the image-only, primary Task 3 flow.
Every external dependency (vision, search) is mocked; this never touches
the network or the blockchain. Confirms candidate iteration actually
skips bad candidates rather than assuming results[0] is correct.
"""

import io
from unittest.mock import patch

from PIL import Image

from src import pipeline as pipeline_mod
from src.models import (
    FaceComparisonResult, FaceEvidence, SearchCandidate, SearchResult,
    SourceEvidence, StageStatus,
)


def _tiny_jpeg_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (10, 10), color="green").save(buf, format="JPEG")
    return buf.getvalue()


def _usable_face_evidence():
    return FaceEvidence(face_count=1, embedding=[0.1] * 128, embedding_sha256="a" * 64, quality_pass=True)


def test_discover_no_serpapi_key_is_rejected(tmp_path):
    image_path = tmp_path / "input.jpg"
    image_path.write_bytes(_tiny_jpeg_bytes())
    config = pipeline_mod.PipelineConfig()
    config.serpapi_key = None
    result = pipeline_mod.discover(image_path=str(image_path), config=config)
    assert result.final_status.value == "rejected"


def test_discover_no_face_is_rejected(tmp_path):
    image_path = tmp_path / "input.jpg"
    image_path.write_bytes(_tiny_jpeg_bytes())
    config = pipeline_mod.PipelineConfig()
    config.serpapi_key = "fake"
    no_face = FaceEvidence(face_count=0, error="no_face_detected")
    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=no_face):
        result = pipeline_mod.discover(image_path=str(image_path), config=config)
    assert result.final_status.value == "rejected"


def test_discover_filters_out_non_social_candidates(tmp_path):
    """A Wikipedia hit must NOT count as a social-media match, even if
    it's the top search result -- this is the core Task 3 distinction."""
    image_path = tmp_path / "input.jpg"
    image_path.write_bytes(_tiny_jpeg_bytes())
    config = pipeline_mod.PipelineConfig()
    config.serpapi_key = "fake"

    search_result = SearchResult(
        provider="serpapi", method="google_lens",
        candidates=[
            SearchCandidate(url="https://en.wikipedia.org/wiki/X", canonical_url="https://en.wikipedia.org/wiki/X", search_rank=0),
            SearchCandidate(url="https://www.nytimes.com/article", canonical_url="https://www.nytimes.com/article", search_rank=1),
        ],
        raw_candidate_count=2, query_image_ref="uploaded:abc",
        visual_match_count=2, exact_match_count=0,
    )
    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch("src.search.SerpApiGoogleLensProvider.search_by_image_bytes", return_value=search_result):
        result = pipeline_mod.discover(image_path=str(image_path), config=config)

    assert result.final_status.value == "no_match"
    assert result.social_candidate_count == 0


def test_discover_skips_unreachable_candidate_and_finds_next(tmp_path):
    """First social candidate is unreachable; discover() must move on to
    the second rather than stopping or picking results[0] blindly."""
    image_path = tmp_path / "input.jpg"
    image_path.write_bytes(_tiny_jpeg_bytes())
    config = pipeline_mod.PipelineConfig()
    config.serpapi_key = "fake"

    candidates = [
        SearchCandidate(url="https://x.com/dead/status/1", canonical_url="https://x.com/dead/status/1", search_rank=0),
        SearchCandidate(url="https://x.com/alive/status/2", canonical_url="https://x.com/alive/status/2", search_rank=1),
    ]
    search_result = SearchResult(
        provider="serpapi", method="google_lens", candidates=candidates,
        raw_candidate_count=2, query_image_ref="uploaded:abc",
        visual_match_count=2, exact_match_count=0,
    )
    unreachable = SourceEvidence(url=candidates[0].url, canonical_url=candidates[0].canonical_url, reachable=False, error="http_error_404")
    reachable = SourceEvidence(
        url=candidates[1].url, canonical_url=candidates[1].canonical_url, reachable=True,
        image_bytes=_tiny_jpeg_bytes(), extraction_method="og:image",
    )
    comparison = FaceComparisonResult(method="face_recognition.face_distance", distance=0.2, threshold=0.6, decision=StageStatus.PASS)

    def fake_fetch(url):
        return unreachable if url == candidates[0].url else reachable

    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch("src.search.SerpApiGoogleLensProvider.search_by_image_bytes", return_value=search_result), \
         patch.object(pipeline_mod.source_mod, "fetch_source", side_effect=fake_fetch), \
         patch.object(pipeline_mod.vision_mod, "compare_faces", return_value=comparison):
        result = pipeline_mod.discover(image_path=str(image_path), config=config)

    assert result.final_status.value == "discovered"
    assert result.match.candidate.url == candidates[1].url  # skipped the dead one


def test_discover_never_touches_blockchain(tmp_path):
    image_path = tmp_path / "input.jpg"
    image_path.write_bytes(_tiny_jpeg_bytes())
    config = pipeline_mod.PipelineConfig()
    config.serpapi_key = "fake"
    with patch.object(pipeline_mod.vision_mod, "analyze_face", return_value=_usable_face_evidence()), \
         patch.object(pipeline_mod, "ChainConfig") as mock_chain_config, \
         patch(
             "src.search.SerpApiGoogleLensProvider.search_by_image_bytes",
             return_value=SearchResult(provider="serpapi", method="google_lens", candidates=[],
                                        raw_candidate_count=0, query_image_ref="uploaded:abc"),
         ):
        pipeline_mod.discover(image_path=str(image_path), config=config)
    mock_chain_config.from_env.assert_not_called()
