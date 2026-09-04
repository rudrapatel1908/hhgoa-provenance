from src.manifest import manifest_sha256_hex, dict_sha256_hex
from src.models import (
    ManifestClaimedSource, ManifestFace, ManifestInput, ManifestRecord,
    ManifestSearch, ManifestVerification, VerificationPolicy,
)


def _sample_policy():
    return VerificationPolicy(
        version="1.1", single_face_required=True, source_access_required=True,
        face_match_required=True, live_search_required=False,
        source_rediscovery_required_for_corroboration=True,
    )


def _sample_manifest(record_id="fixed-id-for-test", title="Original Title"):
    return ManifestRecord(
        schema="hhgoa.media-provenance",
        schema_version=1,
        record_id=record_id,
        created_at="2026-01-01T00:00:00+00:00",
        input=ManifestInput(sha256="a" * 64, mime_type="image/jpeg", width=800, height=600, file_size_bytes=12345),
        face=ManifestFace(
            count=1, embedding_sha256="b" * 64, quality="pass",
            match_method="face_recognition.face_distance", match_distance=0.32,
            match_threshold=0.6, match_decision="pass",
        ),
        claimed_source=ManifestClaimedSource(
            url="https://x.com/user/status/1", canonical_url="https://x.com/user/status/1",
            platform="x.com", title=title,
        ),
        search=ManifestSearch(provider="serpapi", method="google_lens", query_source="original_input_image",
                               candidate_count=8,
                               exact_match_count=1, visual_match_count=8,
                               claimed_source_rediscovered=True),
        verification=ManifestVerification(status="corroborated", method="face_and_source_and_search",
                                           policy=_sample_policy()),
    )


def test_same_manifest_produces_same_hash():
    m1 = _sample_manifest()
    m2 = _sample_manifest()
    assert manifest_sha256_hex(m1) == manifest_sha256_hex(m2)


def test_one_field_change_changes_hash():
    m1 = _sample_manifest(title="Original Title")
    m2 = _sample_manifest(title="Original Title!")  # one-byte-ish change
    assert manifest_sha256_hex(m1) != manifest_sha256_hex(m2)


def test_hash_is_deterministic_hex_format():
    m1 = _sample_manifest()
    h = manifest_sha256_hex(m1)
    assert h.startswith("0x")
    assert len(h) == 66  # 0x + 64 hex chars = 32 bytes


def test_dict_hash_matches_manifest_hash_for_same_content():
    import dataclasses
    m1 = _sample_manifest()
    as_dict = dataclasses.asdict(m1)
    assert dict_sha256_hex(as_dict) == manifest_sha256_hex(m1)


def test_tamper_detection_simulated():
    """Simulates the audit-mode tamper scenario: mutate one field on a
    loaded manifest dict and confirm the hash diverges from the
    'on-chain' hash captured before the mutation."""
    import dataclasses
    original = _sample_manifest()
    onchain_hash = manifest_sha256_hex(original)

    mutated_dict = dataclasses.asdict(original)
    mutated_dict["verification"]["status"] = "on_chain_verified"  # tampered field
    tampered_hash = dict_sha256_hex(mutated_dict)

    assert tampered_hash != onchain_hash
