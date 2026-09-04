"""
Tests pipeline.audit() against real on-disk manifest/verification files
with a mocked chain client. This is the exact scenario that exposed a
real bug during final pre-transaction validation: re-hashing a tampered
manifest and looking up THAT hash on-chain returns "not found", not
"found but mismatched" -- because the tampered hash was never the one
registered. audit() must compare against the ORIGINALLY REGISTERED hash
(read from verification.json), not re-derive a lookup key from
whatever the manifest currently says.
"""

import json
from unittest.mock import MagicMock, patch

from src import pipeline as pipeline_mod
from src.models import OnChainVerification


def _write_manifest_and_verification(tmp_path, manifest_dict, registered_hash, dry_run=False):
    proof_dir = tmp_path / "proof"
    proof_dir.mkdir()
    manifest_path = proof_dir / "manifest.json"
    verification_path = proof_dir / "verification.json"

    with open(manifest_path, "w") as f:
        json.dump(manifest_dict, f)

    with open(verification_path, "w") as f:
        json.dump({
            "final_status": "on_chain_verified",
            "local_manifest_hash": registered_hash,
            "onchain_manifest_hash": registered_hash,
            "contract_address": "0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA",
            "transaction_hash": "0x" + "11" * 32,
            "block_number": 12345,
            "dry_run": dry_run,
        }, f)

    return str(manifest_path), str(verification_path)


def _sample_manifest_dict():
    return {"schema": "hhgoa.media-provenance", "record_id": "abc", "field": "original"}


def test_no_verification_file_means_not_registered(tmp_path):
    proof_dir = tmp_path / "proof"
    proof_dir.mkdir()
    manifest_path = proof_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(_sample_manifest_dict(), f)

    result = pipeline_mod.audit(str(manifest_path))
    assert result["status"] == "NOT_REGISTERED"
    assert result["registered_hash"] is None


def test_dry_run_verification_file_means_not_registered(tmp_path):
    manifest_dict = _sample_manifest_dict()
    registered_hash = pipeline_mod.manifest_mod.dict_sha256_hex(manifest_dict)
    manifest_path, _ = _write_manifest_and_verification(
        tmp_path, manifest_dict, registered_hash, dry_run=True,
    )
    result = pipeline_mod.audit(manifest_path)
    assert result["status"] == "NOT_REGISTERED"


@patch("src.pipeline.RegistryClient")
@patch("src.pipeline.ChainConfig")
def test_untampered_manifest_reports_on_chain_verified(mock_chain_config, mock_client_cls, tmp_path):
    manifest_dict = _sample_manifest_dict()
    registered_hash = pipeline_mod.manifest_mod.dict_sha256_hex(manifest_dict)
    manifest_path, _ = _write_manifest_and_verification(tmp_path, manifest_dict, registered_hash)

    mock_client = MagicMock()
    mock_client.verify_record.return_value = OnChainVerification(
        record_exists=True, onchain_hash_hex=registered_hash,
        local_hash_hex=registered_hash, hashes_match=True,
        onchain_submitter="0xSubmitter", onchain_timestamp=1234567890,
    )
    mock_client_cls.return_value = mock_client

    result = pipeline_mod.audit(manifest_path)
    assert result["status"] == "ON_CHAIN_VERIFIED"
    assert result["local_hash"] == registered_hash


@patch("src.pipeline.RegistryClient")
@patch("src.pipeline.ChainConfig")
def test_tampered_manifest_reports_tamper_detected_not_not_found(mock_chain_config, mock_client_cls, tmp_path):
    """THE critical regression test: mutate the manifest after
    registration, and confirm audit() correctly reports TAMPER_DETECTED
    -- not NOT_FOUND_ON_CHAIN, which was the actual bug."""
    manifest_dict = _sample_manifest_dict()
    registered_hash = pipeline_mod.manifest_mod.dict_sha256_hex(manifest_dict)
    manifest_path, verification_path = _write_manifest_and_verification(
        tmp_path, manifest_dict, registered_hash,
    )

    # Tamper: mutate the manifest on disk AFTER "registration".
    tampered = dict(manifest_dict)
    tampered["field"] = "TAMPERED"
    with open(manifest_path, "w") as f:
        json.dump(tampered, f)

    # The chain still has the ORIGINAL hash registered -- verify_record
    # is called with the registered_hash (read from verification.json),
    # and correctly reports it exists (it does -- it was never touched).
    mock_client = MagicMock()
    mock_client.verify_record.return_value = OnChainVerification(
        record_exists=True, onchain_hash_hex=registered_hash,
        local_hash_hex=registered_hash, hashes_match=True,
        onchain_submitter="0xSubmitter", onchain_timestamp=1234567890,
    )
    mock_client_cls.return_value = mock_client

    result = pipeline_mod.audit(manifest_path)

    assert result["status"] == "TAMPER_DETECTED"
    assert result["status"] != "NOT_FOUND_ON_CHAIN"  # the actual bug this test catches
    assert result["local_hash"] != result["registered_hash"]

    # Confirm the chain was queried using the REGISTERED hash, not a
    # hash re-derived from the tampered manifest.
    called_hash_bytes = mock_client.verify_record.call_args[0][0]
    assert called_hash_bytes == bytes.fromhex(registered_hash[2:])


@patch("src.pipeline.RegistryClient")
@patch("src.pipeline.ChainConfig")
def test_restoring_original_manifest_reports_on_chain_verified_again(mock_chain_config, mock_client_cls, tmp_path):
    manifest_dict = _sample_manifest_dict()
    registered_hash = pipeline_mod.manifest_mod.dict_sha256_hex(manifest_dict)
    manifest_path, _ = _write_manifest_and_verification(tmp_path, manifest_dict, registered_hash)

    mock_client = MagicMock()
    mock_client.verify_record.return_value = OnChainVerification(
        record_exists=True, onchain_hash_hex=registered_hash,
        local_hash_hex=registered_hash, hashes_match=True,
    )
    mock_client_cls.return_value = mock_client

    # Tamper then restore.
    with open(manifest_path, "w") as f:
        json.dump({**manifest_dict, "field": "TAMPERED"}, f)
    assert pipeline_mod.audit(manifest_path)["status"] == "TAMPER_DETECTED"

    with open(manifest_path, "w") as f:
        json.dump(manifest_dict, f)
    assert pipeline_mod.audit(manifest_path)["status"] == "ON_CHAIN_VERIFIED"


@patch("src.pipeline.RegistryClient")
@patch("src.pipeline.ChainConfig")
def test_registered_hash_missing_from_chain_is_reported_explicitly(mock_chain_config, mock_client_cls, tmp_path):
    """An inconsistency (verification.json claims a registration that
    the chain doesn't actually have) must be surfaced honestly, never
    silently folded into either ON_CHAIN_VERIFIED or TAMPER_DETECTED."""
    manifest_dict = _sample_manifest_dict()
    registered_hash = pipeline_mod.manifest_mod.dict_sha256_hex(manifest_dict)
    manifest_path, _ = _write_manifest_and_verification(tmp_path, manifest_dict, registered_hash)

    mock_client = MagicMock()
    mock_client.verify_record.return_value = OnChainVerification(
        record_exists=False, onchain_hash_hex="0x" + "00" * 32,
        local_hash_hex=registered_hash, hashes_match=False,
    )
    mock_client_cls.return_value = mock_client

    result = pipeline_mod.audit(manifest_path)
    assert result["status"] == "REGISTERED_HASH_NOT_FOUND_ON_CHAIN"


def test_audit_never_calls_a_write_method(tmp_path):
    """audit() must be 100% read-only -- confirm no send/register method
    exists on the mocked client that gets called."""
    manifest_dict = _sample_manifest_dict()
    registered_hash = pipeline_mod.manifest_mod.dict_sha256_hex(manifest_dict)
    manifest_path, _ = _write_manifest_and_verification(tmp_path, manifest_dict, registered_hash)

    with patch("src.pipeline.ChainConfig"), patch("src.pipeline.RegistryClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.verify_record.return_value = OnChainVerification(
            record_exists=True, onchain_hash_hex=registered_hash,
            local_hash_hex=registered_hash, hashes_match=True,
        )
        mock_client_cls.return_value = mock_client
        pipeline_mod.audit(manifest_path)

    mock_client.register_record.assert_not_called()
