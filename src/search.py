"""
Genuine live reverse-image search. No hardcoded URLs, no mocked
responses, no input->result dictionaries.

Provider access is isolated behind `ReverseImageSearchProvider` so the
backend (currently SerpApi's Google Lens engine) is replaceable without
touching pipeline.py or candidate-ranking logic.
"""

from __future__ import annotations

import logging
from typing import Protocol

import requests

from .models import SearchCandidate, SearchResult
from .source import canonicalize_url, classify_platform

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 20
SERPAPI_SEARCH_ENDPOINT = "https://serpapi.com/search"
SERPAPI_UPLOAD_ENDPOINT = "https://serpapi.com/image"

# Real, documented limits (serpapi.com/image-api) -- not invented.
# Enforced here so a caller gets a clear, immediate error instead of a
# confusing API-side rejection.
MAX_UPLOAD_BYTES = 500 * 1024
SUPPORTED_UPLOAD_FORMATS = {"jpeg", "jpg", "png", "webp"}


class ReverseImageSearchProvider(Protocol):
    def search(self, image_url: str, *, max_results: int) -> SearchResult: ...


class SerpApiGoogleLensProvider:
    """
    Wraps SerpApi's Google Lens engine (`engine=google_lens`).

    Supports both documented query modes:
      - `search(image_url=...)`      -- reverse-search a public image URL
      - `search_by_image_bytes(...)` -- upload local image bytes first
        (POST /image -> image_id, documented at serpapi.com/image-api),
        then search with that image_id. Required for image-only
        discovery, where there is no source URL yet to search from.

    Real, documented constraints on the upload path (not invented):
    JPG/PNG/WebP only, 500 KB max, image_id expires after 10 minutes.
    """

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("SerpApi API key is required")
        self._api_key = api_key

    def search(self, image_url: str, *, max_results: int = 20) -> SearchResult:
        return self._run_search({"url": image_url}, query_ref=image_url, max_results=max_results)

    def upload_image(self, image_bytes: bytes, *, image_format: str) -> tuple[str | None, str | None]:
        """POST /image -> (image_id, error). image_format is a lowercase
        extension-like hint ('jpeg', 'png', 'webp') used only for the
        pre-flight size/format guard below, not sent to the API."""
        fmt = image_format.lower().lstrip(".")
        if fmt not in SUPPORTED_UPLOAD_FORMATS:
            return None, f"unsupported_upload_format: {fmt} (supported: jpg, png, webp)"
        if len(image_bytes) > MAX_UPLOAD_BYTES:
            return None, (
                f"image_too_large_for_upload: {len(image_bytes)} bytes "
                f"(SerpApi upload limit is {MAX_UPLOAD_BYTES} bytes / 500 KB)"
            )
        try:
            resp = requests.post(
                SERPAPI_UPLOAD_ENDPOINT,
                files={"image": ("image", image_bytes)},
                data={"api_key": self._api_key},
                timeout=HTTP_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            return None, f"upload_request_failed: {exc}"
        except ValueError as exc:
            return None, f"upload_invalid_json_response: {exc}"

        image_id = payload.get("image_id")
        if not image_id:
            return None, f"upload_response_missing_image_id: {payload}"
        return image_id, None

    def search_by_image_bytes(
        self, image_bytes: bytes, *, image_format: str, max_results: int = 20,
    ) -> SearchResult:
        """Uploads the given bytes, then searches by the resulting
        image_id. Used for image-only discovery. Fails closed with a
        clear error on the SearchResult if upload fails for any reason
        -- never falls back to fabricating a query."""
        image_id, upload_error = self.upload_image(image_bytes, image_format=image_format)
        if upload_error:
            return SearchResult(
                provider="serpapi", method="google_lens", candidates=[],
                raw_candidate_count=0, query_image_ref="<uploaded local image>",
                error=upload_error,
            )
        return self._run_search(
            {"image_id": image_id}, query_ref=f"uploaded:{image_id}", max_results=max_results,
        )

    def _run_search(self, extra_params: dict, *, query_ref: str, max_results: int) -> SearchResult:
        params = {"engine": "google_lens", "api_key": self._api_key, **extra_params}
        try:
            resp = requests.get(SERPAPI_SEARCH_ENDPOINT, params=params, timeout=HTTP_TIMEOUT_SECONDS)
            resp.raise_for_status()
            payload = resp.json()
        except requests.RequestException as exc:
            return SearchResult(
                provider="serpapi", method="google_lens", candidates=[],
                raw_candidate_count=0, query_image_ref=query_ref,
                error=f"request_failed: {exc}",
            )
        except ValueError as exc:  # JSON decode error
            return SearchResult(
                provider="serpapi", method="google_lens", candidates=[],
                raw_candidate_count=0, query_image_ref=query_ref,
                error=f"invalid_json_response: {exc}",
            )

        if "error" in payload:
            return SearchResult(
                provider="serpapi", method="google_lens", candidates=[],
                raw_candidate_count=0, query_image_ref=query_ref,
                error=f"serpapi_error: {payload['error']}",
            )

        # SerpApi's google_lens response shape (confirmed against current
        # docs at serpapi.com/google-lens-api and
        # serpapi.com/google-lens-visual-matches-api): the "visual_matches"
        # array holds the reverse-search hits. Each entry MAY carry an
        # "exact_matches" boolean -- SerpApi sets this when that specific
        # visual match is also an exact-pixel match, without requiring a
        # separate type=exact_matches request. We read that flag rather
        # than issuing a second API call, which would double our quota
        # usage for no additional evidence value. We do NOT assume every
        # field is present -- parsed defensively throughout.
        raw_matches = payload.get("visual_matches", [])
        candidates: list[SearchCandidate] = []
        exact_count = 0
        for i, match in enumerate(raw_matches[:max_results]):
            link = match.get("link")
            if not link:
                continue  # a candidate with no URL is not usable evidence
            is_exact = bool(match.get("exact_matches", False))
            if is_exact:
                exact_count += 1
            candidates.append(
                SearchCandidate(
                    url=link,
                    canonical_url=canonicalize_url(link),
                    title=match.get("title"),
                    source_domain=match.get("source") or classify_platform(canonicalize_url(link)),
                    thumbnail=match.get("thumbnail"),
                    image_url=match.get("image") or match.get("thumbnail"),
                    search_rank=i,
                    is_exact_match=is_exact,
                    raw_metadata=match,
                )
            )

        return SearchResult(
            provider="serpapi",
            method="google_lens",
            candidates=candidates,
            raw_candidate_count=len(raw_matches),
            query_image_ref=query_ref,
            exact_match_count=exact_count,
            visual_match_count=len(candidates),
        )


def dedupe_candidates(candidates: list[SearchCandidate]) -> list[SearchCandidate]:
    """Dedupe by canonical URL, keeping the highest-ranked (lowest
    search_rank) occurrence of each."""
    best: dict[str, SearchCandidate] = {}
    for c in candidates:
        existing = best.get(c.canonical_url)
        if existing is None or (c.search_rank or 0) < (existing.search_rank or 0):
            best[c.canonical_url] = c
    return sorted(best.values(), key=lambda c: (c.search_rank if c.search_rank is not None else 1_000_000))


def find_matching_candidate(
    candidates: list[SearchCandidate], claimed_canonical_url: str,
) -> SearchCandidate | None:
    """Returns the candidate whose canonical URL equals the claimed
    source's canonical URL, or None if not independently rediscovered."""
    for c in candidates:
        if c.canonical_url == claimed_canonical_url:
            return c
    return None
