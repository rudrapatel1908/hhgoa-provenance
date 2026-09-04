"""
Fetching and extracting evidence from a user-claimed public source URL.

Scope: publicly accessible / authorized material only. This module does
NOT attempt to bypass authentication, paywalls, or robots restrictions --
if a page can't be read as an anonymous client would read it, extraction
fails cleanly rather than trying harder.
"""

from __future__ import annotations

import logging
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup

from .models import SourceEvidence

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10
MAX_DOWNLOAD_BYTES = 15 * 1024 * 1024  # 15 MB cap
USER_AGENT = "hhgoa-provenance-bot/1.0 (+https://github.com/) verification research tool"

# Tracking / session query params stripped during canonicalization.
# Deliberately conservative -- anything not in this list is preserved,
# since stripping unknown params could change the identified resource.
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "igshid", "fbclid", "gclid", "ref", "s", "si",
}

# Platform host aliases treated as equivalent for corroboration purposes.
# Documented explicitly -- do NOT extend this casually, since over-broad
# equivalence weakens the "independently rediscovered" guarantee.
_HOST_ALIASES = {
    "twitter.com": "x.com",
    "www.twitter.com": "x.com",
    "www.x.com": "x.com",
    "mobile.twitter.com": "x.com",
    "m.twitter.com": "x.com",
    "www.instagram.com": "instagram.com",
    "www.facebook.com": "facebook.com",
    "m.facebook.com": "facebook.com",
}


def canonicalize_url(raw_url: str) -> str:
    """
    Normalize a URL for equivalence comparison:
      - lowercase scheme/host
      - map known platform host aliases (twitter.com -> x.com, etc.)
      - strip URL fragment
      - strip known tracking query params (keep everything else, sorted)
      - drop trailing slash on the path (except root "/")

    This intentionally does NOT touch path casing, unknown query params,
    or path segments -- over-normalization risks treating two DIFFERENT
    resources as equivalent.
    """
    parts = urlsplit(raw_url.strip())
    scheme = parts.scheme.lower() or "https"
    host = parts.hostname.lower() if parts.hostname else ""
    host = _HOST_ALIASES.get(host, host)

    # Empty path ("https://example.com") and root path ("https://example.com/")
    # identify the same resource -- normalize both to "".
    path = parts.path
    if path == "/":
        path = ""
    elif len(path) > 1 and path.endswith("/"):
        path = path[:-1]

    kept_params = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in _TRACKING_PARAMS
    )
    query = urlencode(kept_params)

    return urlunsplit((scheme, host, path, query, ""))  # fragment always dropped


def classify_platform(canonical_url: str) -> str:
    """Hostname-suffix based classification -- NOT substring matching.
    'x.com' must not match 'fox.com' just because the characters appear
    inside it; we only match on the actual domain or a subdomain of it."""
    host = urlsplit(canonical_url).hostname or ""
    for known in ("x.com", "instagram.com", "facebook.com", "reddit.com",
                  "youtube.com", "linkedin.com", "tiktok.com", "threads.net"):
        if host == known or host.endswith("." + known):
            return known
    return host or "unknown"


# Platforms treated as "social media" for Task 3's discovery requirement.
# Wikipedia, news sites, blogs, etc. are legitimate provenance sources but
# do NOT satisfy the specific "matching social-media post" requirement.
_SOCIAL_PLATFORMS = {
    "x.com", "twitter.com", "instagram.com", "facebook.com",
    "linkedin.com", "youtube.com", "threads.net", "tiktok.com",
}


def is_social_platform(canonical_url: str) -> bool:
    """Hostname-suffix check against a real allowlist -- same matching
    discipline as classify_platform, not a fragile substring check."""
    host = urlsplit(canonical_url).hostname or ""
    return any(host == p or host.endswith("." + p) for p in _SOCIAL_PLATFORMS)


def fetch_source(url: str) -> SourceEvidence:
    """
    Fetch the claimed source page, validate it, and extract the most
    relevant image via a layered strategy:
      Open Graph image -> Twitter card image -> first <img> tag
    Fails cleanly (reachable=False / image_url=None) rather than guessing.
    """
    canonical = canonicalize_url(url)
    platform = classify_platform(canonical)

    try:
        resp = requests.get(
            url,
            timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
            stream=True,
        )
    except requests.RequestException as exc:
        return SourceEvidence(
            url=url, canonical_url=canonical, reachable=False,
            platform=platform, error=f"request_failed: {exc}",
        )

    if resp.status_code >= 400:
        return SourceEvidence(
            url=url, canonical_url=canonical, reachable=False,
            http_status=resp.status_code, platform=platform,
            error=f"http_error_{resp.status_code}",
        )

    content_type = resp.headers.get("Content-Type", "")
    if "text/html" not in content_type:
        return SourceEvidence(
            url=url, canonical_url=canonical, reachable=True,
            http_status=resp.status_code, content_type=content_type,
            platform=platform, error="unexpected_content_type",
        )

    raw = resp.raw.read(MAX_DOWNLOAD_BYTES + 1, decode_content=True)
    if len(raw) > MAX_DOWNLOAD_BYTES:
        return SourceEvidence(
            url=url, canonical_url=canonical, reachable=True,
            http_status=resp.status_code, content_type=content_type,
            platform=platform, error="content_too_large",
        )

    soup = BeautifulSoup(raw, "html.parser")
    title = soup.title.string.strip() if soup.title and soup.title.string else None

    image_url, method = _extract_image(soup, base_url=resp.url)

    evidence = SourceEvidence(
        url=url,
        canonical_url=canonical,
        reachable=True,
        http_status=resp.status_code,
        content_type=content_type,
        platform=platform,
        title=title,
        image_url=image_url,
        extraction_method=method,
    )

    if image_url:
        evidence.image_bytes = _download_image(image_url)
        if evidence.image_bytes is None:
            evidence.error = "image_download_failed"
    else:
        evidence.error = "no_image_found_on_page"

    return evidence


def _extract_image(soup: BeautifulSoup, base_url: str):
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return _absolutize(og["content"], base_url), "og:image"

    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return _absolutize(tw["content"], base_url), "twitter:image"

    img = soup.find("img", src=True)
    if img:
        return _absolutize(img["src"], base_url), "img_tag"

    return None, None


def _absolutize(maybe_relative: str, base_url: str) -> str:
    from urllib.parse import urljoin
    return urljoin(base_url, maybe_relative)


def _download_image(image_url: str) -> bytes | None:
    try:
        resp = requests.get(
            image_url, timeout=HTTP_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT}, stream=True,
        )
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "")
        if not ct.startswith("image/"):
            return None
        data = resp.raw.read(MAX_DOWNLOAD_BYTES + 1, decode_content=True)
        if len(data) > MAX_DOWNLOAD_BYTES:
            return None
        return data
    except requests.RequestException as exc:
        logger.warning("image download failed for %s: %s", image_url, exc)
        return None


def urls_equivalent(url_a: str, url_b: str) -> bool:
    """Platform-aware equivalence check used to decide whether a search
    candidate 'is' the claimed source. Compares canonical forms only."""
    return canonicalize_url(url_a) == canonicalize_url(url_b)
