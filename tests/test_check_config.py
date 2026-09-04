"""Tests the check-config command: must be 100% read-only, never call a
write method, and surface config/ABI/contract errors plainly."""

from unittest.mock import MagicMock, patch

from src import cli as cli_mod


def test_check_config_success_never_calls_write_method(capsys, monkeypatch):
    for var in ("POLYGON_AMOY_RPC_URL", "CHAIN_ID", "CONTRACT_ADDRESS", "PRIVATE_KEY"):
        monkeypatch.setenv(var, "dummy")
    monkeypatch.setenv("CHAIN_ID", "80002")
    monkeypatch.setenv("PRIVATE_KEY", "0x" + "1" * 64)
    monkeypatch.setenv("CONTRACT_ADDRESS", "0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA")

    mock_client = MagicMock()
    mock_client.address = "0xSomeAddress"
    mock_client.verify_record.return_value = None

    with patch("src.blockchain.ChainConfig.from_env") as mock_from_env, \
         patch("src.blockchain.RegistryClient", return_value=mock_client):
        mock_from_env.return_value = MagicMock(
            rpc_url="https://fake-rpc", chain_id=80002,
            contract_address="0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA",
        )
        exit_code = cli_mod.main(["check-config"])

    assert exit_code == 0
    mock_client.register_record.assert_not_called()
    out = capsys.readouterr().out
    assert "No transaction sent" in out


def test_check_config_missing_env_vars_fails_cleanly(monkeypatch):
    # main() unconditionally calls load_dotenv() on startup, which reads
    # the real .env from disk. Without stubbing it out, deleting the vars
    # here would just get silently undone the moment main() runs -- so
    # this test would end up validating against the developer's real
    # config instead of a genuinely empty one. Stub load_dotenv() as a
    # no-op so this test is isolated from whatever .env happens to exist
    # on the machine running it.
    monkeypatch.setattr(cli_mod, "load_dotenv", lambda *a, **k: None)
    for var in ("POLYGON_AMOY_RPC_URL", "CHAIN_ID", "CONTRACT_ADDRESS", "PRIVATE_KEY"):
        monkeypatch.delenv(var, raising=False)
    exit_code = cli_mod.main(["check-config"])
    assert exit_code == 1