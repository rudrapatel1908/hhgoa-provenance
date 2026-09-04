from unittest.mock import patch, MagicMock

from src.search import SerpApiGoogleLensProvider, dedupe_candidates, find_matching_candidate
from src.models import SearchCandidate


def _mock_response(json_payload, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_payload
    resp.raise_for_status = MagicMock()
    if not status_ok:
        resp.raise_for_status.side_effect = Exception("http error")
    return resp


@patch("src.search.requests.get")
def test_missing_fields_handled_gracefully(mock_get):
    mock_get.return_value = _mock_response({
        "visual_matches": [
            {"link": "https://example.com/a"},          # no title/source/image
            {"title": "No link here"},                    # missing link -> dropped
            {"link": "https://example.com/b", "title": "B", "source": "example.com"},
        ]
    })
    provider = SerpApiGoogleLensProvider(api_key="fake")
    result = provider.search("https://input.example/image.jpg", max_results=10)

    assert result.succeeded
    assert len(result.candidates) == 2  # the fieldless-link entry was dropped
    assert result.candidates[0].url == "https://example.com/a"


@patch("src.search.requests.get")
def test_exact_match_flag_parsed_without_extra_request(mock_get):
    """SerpApi marks some visual_matches entries with exact_matches=true.
    We must read that flag from the single response we already have,
    never issue a second type=exact_matches request (protects API quota)."""
    mock_get.return_value = _mock_response({
        "visual_matches": [
            {"link": "https://example.com/a", "exact_matches": True},
            {"link": "https://example.com/b", "exact_matches": False},
            {"link": "https://example.com/c"},  # flag absent -> defaults False
        ]
    })
    provider = SerpApiGoogleLensProvider(api_key="fake")
    result = provider.search("https://input.example/image.jpg", max_results=10)

    assert mock_get.call_count == 1  # exactly one HTTP call, no second request
    assert result.exact_match_count == 1
    assert result.visual_match_count == 3
    assert result.candidates[0].is_exact_match is True
    assert result.candidates[1].is_exact_match is False
    assert result.candidates[2].is_exact_match is False


@patch("src.search.requests.get")
def test_empty_results(mock_get):
    mock_get.return_value = _mock_response({"visual_matches": []})
    provider = SerpApiGoogleLensProvider(api_key="fake")
    result = provider.search("https://input.example/image.jpg", max_results=10)
    assert result.succeeded
    assert result.candidates == []


@patch("src.search.requests.get")
def test_serpapi_error_field_surfaced(mock_get):
    mock_get.return_value = _mock_response({"error": "Invalid API key."})
    provider = SerpApiGoogleLensProvider(api_key="fake")
    result = provider.search("https://input.example/image.jpg", max_results=10)
    assert not result.succeeded
    assert "Invalid API key" in result.error


def test_dedupe_keeps_best_rank():
    candidates = [
        SearchCandidate(url="https://x.com/a", canonical_url="https://x.com/a", search_rank=3),
        SearchCandidate(url="https://x.com/a?utm_source=x", canonical_url="https://x.com/a", search_rank=0),
    ]
    deduped = dedupe_candidates(candidates)
    assert len(deduped) == 1
    assert deduped[0].search_rank == 0


def test_malformed_url_does_not_crash_canonicalization():
    from src.source import canonicalize_url
    # No scheme -- should not raise
    result = canonicalize_url("not a url at all")
    assert isinstance(result, str)


def test_find_matching_candidate():
    candidates = [
        SearchCandidate(url="https://x.com/a", canonical_url="https://x.com/a"),
        SearchCandidate(url="https://x.com/b", canonical_url="https://x.com/b"),
    ]
    match = find_matching_candidate(candidates, "https://x.com/b")
    assert match is not None
    assert match.url == "https://x.com/b"

    no_match = find_matching_candidate(candidates, "https://x.com/c")
    assert no_match is None


# --- upload-based search (real, documented SerpApi /image endpoint) ---

@patch("src.search.requests.post")
def test_upload_image_success(mock_post):
    mock_post.return_value = _mock_response({
        "message": "Image uploaded successfully.", "image_id": "abc123",
    })
    provider = SerpApiGoogleLensProvider(api_key="fake")
    image_id, error = provider.upload_image(b"x" * 100, image_format="jpeg")
    assert image_id == "abc123"
    assert error is None


def test_upload_image_rejects_oversized_file_without_network_call():
    provider = SerpApiGoogleLensProvider(api_key="fake")
    with patch("src.search.requests.post") as mock_post:
        image_id, error = provider.upload_image(
            b"x" * (501 * 1024), image_format="jpeg",
        )
    mock_post.assert_not_called()  # pre-flight guard, no wasted request
    assert image_id is None
    assert "too_large" in error


def test_upload_image_rejects_unsupported_format_without_network_call():
    provider = SerpApiGoogleLensProvider(api_key="fake")
    with patch("src.search.requests.post") as mock_post:
        image_id, error = provider.upload_image(b"x" * 100, image_format="gif")
    mock_post.assert_not_called()
    assert image_id is None
    assert "unsupported_upload_format" in error


@patch("src.search.requests.post")
def test_upload_image_missing_image_id_in_response(mock_post):
    mock_post.return_value = _mock_response({"message": "ok"})  # no image_id
    provider = SerpApiGoogleLensProvider(api_key="fake")
    image_id, error = provider.upload_image(b"x" * 100, image_format="png")
    assert image_id is None
    assert "missing_image_id" in error


@patch("src.search.requests.get")
@patch("src.search.requests.post")
def test_search_by_image_bytes_uses_image_id_not_url(mock_post, mock_get):
    mock_post.return_value = _mock_response({"image_id": "xyz789"})
    mock_get.return_value = _mock_response({"visual_matches": [
        {"link": "https://x.com/found", "exact_matches": True},
    ]})

    provider = SerpApiGoogleLensProvider(api_key="fake")
    result = provider.search_by_image_bytes(b"x" * 100, image_format="jpg")

    assert result.succeeded
    assert result.candidates[0].url == "https://x.com/found"
    # confirm the search call used image_id, not a url param
    _, kwargs = mock_get.call_args
    assert kwargs["params"].get("image_id") == "xyz789"
    assert "url" not in kwargs["params"]


def test_search_by_image_bytes_fails_closed_on_upload_error():
    provider = SerpApiGoogleLensProvider(api_key="fake")
    with patch("src.search.requests.get") as mock_get:
        result = provider.search_by_image_bytes(b"x" * (600 * 1024), image_format="jpeg")
    mock_get.assert_not_called()  # never searches if upload failed
    assert not result.succeeded
    assert "too_large" in result.error
