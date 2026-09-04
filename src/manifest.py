"""
Canonical manifest construction and deterministic SHA-256 hashing.

Canonicalization method (must never change without a schema_version bump):
  - json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
  - encoded as UTF-8
  - SHA-256 over those exact bytes

A one-byte change anywhere in the manifest MUST change the digest; the
same manifest MUST always produce the same digest. Both are covered by
tests/test_manifest.py.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json

from .models import ManifestRecord


def canonical_json_bytes(manifest: ManifestRecord) -> bytes:
    """Serialize a ManifestRecord to canonical JSON bytes."""
    as_dict = dataclasses.asdict(manifest)
    return json.dumps(
        as_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def manifest_sha256(manifest: ManifestRecord) -> bytes:
    """32-byte SHA-256 digest of the canonical manifest -- this is what
    gets passed to the contract as `bytes32 recordHash`."""
    return hashlib.sha256(canonical_json_bytes(manifest)).digest()


def manifest_sha256_hex(manifest: ManifestRecord) -> str:
    return "0x" + manifest_sha256(manifest).hex()


def dict_sha256_hex(as_dict: dict) -> str:
    """Same canonicalization applied to an arbitrary dict -- used by
    audit mode to re-hash a manifest.json loaded from disk, so the audit
    path exercises the exact same code as the registration path."""
    encoded = json.dumps(
        as_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return "0x" + hashlib.sha256(encoded).hexdigest()
