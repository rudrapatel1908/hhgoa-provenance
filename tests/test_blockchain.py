"""
Tests blockchain.py against a mocked web3.Web3 instance -- no real RPC
calls. Covers config validation, the duplicate-record revert path, and
read-after-write verification logic (hash match / mismatch).
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from src.blockchain import ChainConfig, ConfigError, RegistryClient, TransactionFailed


def test_chain_config_missing_vars_raises(monkeypatch):
    monkeypatch.delenv("POLYGON_AMOY_RPC_URL", raising=False)
    monkeypatch.delenv("CHAIN_ID", raising=False)
    monkeypatch.delenv("CONTRACT_ADDRESS", raising=False)
    monkeypatch.delenv("PRIVATE_KEY", raising=False)
    with pytest.raises(ConfigError):
        ChainConfig.from_env()


def test_chain_config_loads_when_complete(monkeypatch):
    monkeypatch.setenv("POLYGON_AMOY_RPC_URL", "https://rpc.example/amoy")
    monkeypatch.setenv("CHAIN_ID", "80002")
    monkeypatch.setenv("CONTRACT_ADDRESS", "0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA")
    monkeypatch.setenv("PRIVATE_KEY", "0x" + "1" * 64)
    cfg = ChainConfig.from_env()
    assert cfg.chain_id == 80002


@patch("src.blockchain.Web3")
@patch("src.blockchain._load_abi", return_value=[])
def test_verify_record_hash_match(mock_abi, mock_web3_cls, monkeypatch):
    monkeypatch.setenv("POLYGON_AMOY_RPC_URL", "https://rpc.example/amoy")
    monkeypatch.setenv("CHAIN_ID", "80002")
    monkeypatch.setenv("CONTRACT_ADDRESS", "0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA")
    monkeypatch.setenv("PRIVATE_KEY", "0x" + "1" * 64)

    mock_w3_instance = MagicMock()
    mock_w3_instance.is_connected.return_value = True
    mock_web3_cls.return_value = mock_w3_instance
    mock_web3_cls.to_checksum_address.side_effect = lambda x: x
    mock_web3_cls.HTTPProvider.return_value = MagicMock()

    record_hash = bytes.fromhex("aa" * 32)
    mock_w3_instance.eth.contract.return_value.functions.verifyRecord.return_value.call.return_value = (
        True, "0xSubmitter", 1234567890,
    )

    config = ChainConfig.from_env()
    client = RegistryClient(config)
    local_hash_hex = "0x" + record_hash.hex()
    result = client.verify_record(record_hash, local_hash_hex)

    assert result.record_exists is True
    assert result.hashes_match is True


@patch("src.blockchain.Web3")
@patch("src.blockchain._load_abi", return_value=[])
def test_verify_record_not_found(mock_abi, mock_web3_cls, monkeypatch):
    monkeypatch.setenv("POLYGON_AMOY_RPC_URL", "https://rpc.example/amoy")
    monkeypatch.setenv("CHAIN_ID", "80002")
    monkeypatch.setenv("CONTRACT_ADDRESS", "0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA")
    monkeypatch.setenv("PRIVATE_KEY", "0x" + "1" * 64)

    mock_w3_instance = MagicMock()
    mock_w3_instance.is_connected.return_value = True
    mock_web3_cls.return_value = mock_w3_instance
    mock_web3_cls.to_checksum_address.side_effect = lambda x: x
    mock_web3_cls.HTTPProvider.return_value = MagicMock()

    mock_w3_instance.eth.contract.return_value.functions.verifyRecord.return_value.call.return_value = (
        False, "0x0000000000000000000000000000000000000000", 0,
    )

    config = ChainConfig.from_env()
    client = RegistryClient(config)
    record_hash = bytes.fromhex("bb" * 32)
    result = client.verify_record(record_hash, "0x" + record_hash.hex())

    assert result.record_exists is False
    assert result.hashes_match is False


@patch("src.blockchain.Web3")
@patch("src.blockchain._load_abi", return_value=[])
def test_register_record_reverts_on_gas_estimation_failure(mock_abi, mock_web3_cls, monkeypatch):
    """Simulates the contract's DuplicateRecord() custom error surfacing
    during gas estimation (the standard way reverts are caught pre-send)."""
    monkeypatch.setenv("POLYGON_AMOY_RPC_URL", "https://rpc.example/amoy")
    monkeypatch.setenv("CHAIN_ID", "80002")
    monkeypatch.setenv("CONTRACT_ADDRESS", "0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA")
    monkeypatch.setenv("PRIVATE_KEY", "0x" + "1" * 64)

    mock_w3_instance = MagicMock()
    mock_w3_instance.is_connected.return_value = True
    mock_web3_cls.return_value = mock_w3_instance
    mock_web3_cls.to_checksum_address.side_effect = lambda x: x
    mock_web3_cls.HTTPProvider.return_value = MagicMock()

    mock_w3_instance.eth.contract.return_value.functions.registerRecord.return_value.estimate_gas.side_effect = (
        Exception("execution reverted: DuplicateRecord")
    )

    config = ChainConfig.from_env()
    client = RegistryClient(config)

    with pytest.raises(TransactionFailed, match="gas estimation failed"):
        client.register_record(bytes.fromhex("cc" * 32), "")
