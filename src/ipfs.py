"""
IPFS pinning via Pinata. Content-addressed manifest storage only --
NOT the source of truth for verification (the blockchain digest is).

If Pinata credentials are absent, `pin_manifest` returns a controlled
`IpfsNotConfigured` result rather than crashing or silently no-op'ing in
a way that could be mistaken for success.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

PINATA_PIN_JSON_ENDPOINT = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
HTTP_TIMEOUT_SECONDS = 20


@dataclass
class IpfsPinResult:
    pinned: bool
    cid: Optional[str] = None
    error: Optional[str] = None


def pin_manifest(manifest_dict: dict, *, jwt: Optional[str]) -> IpfsPinResult:
    """
    Pin the canonical manifest JSON to IPFS via Pinata's JWT-authenticated
    endpoint. Returns a result object rather than raising, so callers
    (the pipeline) can decide whether an IPFS failure should block
    blockchain registration (by policy, it does not -- see README
    "Privacy model" / IPFS section).
    """
    if not jwt:
        return IpfsPinResult(pinned=False, error="ipfs_not_configured: PINATA_JWT is unset")

    try:
        resp = requests.post(
            PINATA_PIN_JSON_ENDPOINT,
            json={"pinataContent": manifest_dict},
            headers={"Authorization": f"Bearer {jwt}"},
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        resp.raise_for_status()
        payload = resp.json()
    except requests.RequestException as exc:
        logger.warning("IPFS pin failed: %s", exc)
        return IpfsPinResult(pinned=False, error=f"pinata_request_failed: {exc}")
    except ValueError as exc:
        return IpfsPinResult(pinned=False, error=f"pinata_invalid_json: {exc}")

    cid = payload.get("IpfsHash")
    if not cid:
        return IpfsPinResult(pinned=False, error="pinata_response_missing_ipfs_hash")

    return IpfsPinResult(pinned=True, cid=cid)
