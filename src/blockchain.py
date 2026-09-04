"""
Polygon Amoy interaction via web3.py: config load, tx build/sign/send,
receipt confirmation, and independent read-only verification.

Hard rules enforced in this module:
  - a private key is never logged or printed
  - "registered" is never claimed before a receipt with status == 1
  - the on-chain verification read is a SEPARATE call made AFTER
    confirmation, not inferred from the send
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from web3 import Web3
from web3.exceptions import TimeExhausted

from .models import BlockchainRegistration, OnChainVerification

logger = logging.getLogger(__name__)

TX_RECEIPT_TIMEOUT_SECONDS = 120
TX_POLL_INTERVAL_SECONDS = 3

_ABI_PATH = Path(__file__).parent.parent / "contracts" / "FaceVerificationRegistry.abi.json"


class ConfigError(RuntimeError):
    pass


class TransactionFailed(RuntimeError):
    pass


@dataclass
class ChainConfig:
    rpc_url: str
    chain_id: int
    contract_address: str
    private_key: str
    explorer_base_url: str

    @classmethod
    def from_env(cls) -> "ChainConfig":
        rpc_url = os.environ.get("POLYGON_AMOY_RPC_URL")
        chain_id = os.environ.get("CHAIN_ID")
        contract_address = os.environ.get("CONTRACT_ADDRESS")
        private_key = os.environ.get("PRIVATE_KEY")
        explorer_base_url = os.environ.get("EXPLORER_BASE_URL", "https://amoy.polygonscan.com/tx/")

        missing = [
            name for name, val in [
                ("POLYGON_AMOY_RPC_URL", rpc_url),
                ("CHAIN_ID", chain_id),
                ("CONTRACT_ADDRESS", contract_address),
                ("PRIVATE_KEY", private_key),
            ] if not val
        ]
        if missing:
            raise ConfigError(f"missing required environment variables: {', '.join(missing)}")

        return cls(
            rpc_url=rpc_url,
            chain_id=int(chain_id),
            contract_address=Web3.to_checksum_address(contract_address),
            private_key=private_key,
            explorer_base_url=explorer_base_url,
        )


def _load_abi() -> list:
    if not _ABI_PATH.exists():
        raise ConfigError(
            f"contract ABI not found at {_ABI_PATH}. "
            "Compile FaceVerificationRegistry.sol and place the ABI there "
            "(see README 'Remix deployment')."
        )
    with open(_ABI_PATH) as f:
        return json.load(f)


class RegistryClient:
    def __init__(self, config: ChainConfig):
        self._config = config
        self._w3 = Web3(Web3.HTTPProvider(config.rpc_url, request_kwargs={"timeout": 30}))
        if not self._w3.is_connected():
            raise ConfigError(f"could not connect to RPC endpoint: {config.rpc_url}")

        self._account = self._w3.eth.account.from_key(config.private_key)
        self._contract = self._w3.eth.contract(
            address=config.contract_address, abi=_load_abi()
        )

    @property
    def address(self) -> str:
        return self._account.address

    def register_record(self, record_hash: bytes, manifest_uri: str) -> BlockchainRegistration:
        """Build, sign, send, and wait for confirmation of a
        registerRecord() transaction. Raises TransactionFailed if the
        receipt status is not 1 -- callers must never advance past this
        without a confirmed, successful receipt."""
        nonce = self._w3.eth.get_transaction_count(self._account.address)

        try:
            gas_estimate = self._contract.functions.registerRecord(
                record_hash, manifest_uri
            ).estimate_gas({"from": self._account.address})
        except Exception as exc:
            raise TransactionFailed(f"gas estimation failed (would revert?): {exc}") from exc

        try:
            fee_history = self._w3.eth.fee_history(1, "latest")
            base_fee = fee_history["baseFeePerGas"][-1]
        except Exception:
            base_fee = self._w3.eth.gas_price

        priority_fee = self._w3.to_wei(30, "gwei")  # Amoy typically needs a nontrivial tip
        max_fee = base_fee * 2 + priority_fee

        tx = self._contract.functions.registerRecord(record_hash, manifest_uri).build_transaction({
            "from": self._account.address,
            "nonce": nonce,
            "gas": int(gas_estimate * 1.2),
            "maxFeePerGas": max_fee,
            "maxPriorityFeePerGas": priority_fee,
            "chainId": self._config.chain_id,
        })

        signed = self._account.sign_transaction(tx)
        tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)

        try:
            receipt = self._w3.eth.wait_for_transaction_receipt(
                tx_hash, timeout=TX_RECEIPT_TIMEOUT_SECONDS, poll_latency=TX_POLL_INTERVAL_SECONDS
            )
        except TimeExhausted as exc:
            raise TransactionFailed(
                f"receipt not confirmed within {TX_RECEIPT_TIMEOUT_SECONDS}s "
                f"(tx {tx_hash.hex()} may still confirm later -- check explorer)"
            ) from exc

        if receipt.status != 1:
            raise TransactionFailed(f"transaction reverted (status={receipt.status}): {tx_hash.hex()}")

        return BlockchainRegistration(
            tx_hash=tx_hash.hex(),
            block_number=receipt.blockNumber,
            contract_address=self._config.contract_address,
            submitter=self._account.address,
            receipt_status=receipt.status,
        )

    def verify_record(self, record_hash: bytes, local_hash_hex: str) -> OnChainVerification:
        """Independent read-only call -- does NOT trust the result of a
        prior register_record() call in this same process. Re-derives
        everything from chain state."""
        exists, submitter, timestamp = self._contract.functions.verifyRecord(record_hash).call()
        onchain_hash_hex = "0x" + record_hash.hex() if exists else "0x" + "00" * 32

        return OnChainVerification(
            record_exists=exists,
            onchain_hash_hex=onchain_hash_hex,
            local_hash_hex=local_hash_hex,
            hashes_match=exists and onchain_hash_hex.lower() == local_hash_hex.lower(),
            onchain_submitter=submitter if exists else None,
            onchain_timestamp=timestamp if exists else None,
        )

    def explorer_url(self, tx_hash: str) -> str:
        return self._config.explorer_base_url.rstrip("/") + "/" + tx_hash
