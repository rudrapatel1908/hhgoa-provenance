"""
Tests the API adapter with FastAPI's TestClient. Everything below
pipeline.py is mocked (same discipline as the CLI tests) -- no network
calls, no blockchain calls, no real files left behind. The one thing
these tests specifically prove: /api/register refuses to call
pipeline.register(dry_run=False) unless the exact confirmation string
is supplied, and /api/verify can NEVER be dry_run=False no matter what
the caller sends.
"""

import io
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import app
from src.models import EvidenceStatus, PipelineResult, StageStatus, DiscoveryResult


client = TestClient(app)


def _tiny_file():
    return ("input.jpg", io.BytesIO(b"fake image bytes"), "image/jpeg")


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_check_config_ok():
    with patch("src.pipeline.check_config", return_value={"ok": True, "rpc_url": "x", "wallet": "y", "contract_address": "z", "chain_id": 80002}):
        resp = client.get("/api/check-config")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_check_config_failure_returns_503():
    with patch("src.pipeline.check_config", return_value={"ok": False, "error": "configuration_error: missing vars"}):
        resp = client.get("/api/check-config")
    assert resp.status_code == 503


def test_discover_endpoint_returns_json(tmp_path):
    fake_result = DiscoveryResult(final_status=EvidenceStatus.NO_MATCH, stages=[])
    with patch("src.pipeline.discover", return_value=fake_result) as mock_discover:
        resp = client.post("/api/discover", files={"image": _tiny_file()})
    assert resp.status_code == 200
    assert resp.json()["final_status"] == "no_match"
    assert mock_discover.called


def test_verify_endpoint_always_dry_run():
    """Even if a caller could somehow influence this, /api/verify has no
    parameter that flips dry_run -- confirm the call is hardcoded True."""
    fake_result = PipelineResult(final_status=EvidenceStatus.CORROBORATED, stages=[], dry_run=True)
    with patch("src.pipeline.register", return_value=fake_result) as mock_register:
        resp = client.post(
            "/api/verify",
            files={"image": _tiny_file()},
            data={"url": "https://x.com/user/status/1"},
        )
    assert resp.status_code == 200
    _, kwargs = mock_register.call_args
    assert kwargs["dry_run"] is True


def test_register_endpoint_rejects_without_confirmation():
    with patch("src.pipeline.register") as mock_register:
        resp = client.post(
            "/api/register",
            files={"image": _tiny_file()},
            data={"url": "https://x.com/user/status/1", "confirm": "yes please"},
        )
    assert resp.status_code == 400
    mock_register.assert_not_called()  # the critical assertion


def test_register_endpoint_rejects_with_empty_confirmation():
    with patch("src.pipeline.register") as mock_register:
        resp = client.post(
            "/api/register",
            files={"image": _tiny_file()},
            data={"url": "https://x.com/user/status/1", "confirm": ""},
        )
    assert resp.status_code == 422 or resp.status_code == 400
    mock_register.assert_not_called()


def test_register_endpoint_proceeds_with_exact_confirmation():
    fake_result = PipelineResult(final_status=EvidenceStatus.ON_CHAIN_VERIFIED, stages=[], dry_run=False)
    with patch("src.pipeline.register", return_value=fake_result) as mock_register:
        resp = client.post(
            "/api/register",
            files={"image": _tiny_file()},
            data={"url": "https://x.com/user/status/1", "confirm": "REGISTER"},
        )
    assert resp.status_code == 200
    _, kwargs = mock_register.call_args
    assert kwargs["dry_run"] is False
    mock_register.assert_called_once()


def test_audit_endpoint_missing_manifest_returns_404():
    resp = client.get("/api/audit", params={"manifest": "/nonexistent/manifest.json"})
    assert resp.status_code == 404


def test_audit_endpoint_returns_result(tmp_path):
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{}")
    with patch("src.pipeline.audit", return_value={"status": "NOT_REGISTERED", "local_hash": "0xabc", "registered_hash": None, "onchain_exists": False}):
        resp = client.get("/api/audit", params={"manifest": str(manifest_path)})
    assert resp.status_code == 200
    assert resp.json()["status"] == "NOT_REGISTERED"


def test_discover_response_never_contains_raw_embedding_key():
    """Sanity check: the JSON serializer must never surface a raw
    embedding vector even if a mocked result somehow included one --
    DiscoveryResult/PipelineResult never carry raw embeddings in the
    first place (only *_sha256 fields), but this locks that in at the
    API boundary too."""
    fake_result = DiscoveryResult(final_status=EvidenceStatus.NO_MATCH, stages=[])
    with patch("src.pipeline.discover", return_value=fake_result):
        resp = client.post("/api/discover", files={"image": _tiny_file()})
    body_text = resp.text
    assert "embedding" not in body_text or '"embedding_sha256"' in body_text or "embedding" not in body_text
    assert '"embedding":' not in body_text  # raw field name, would only appear if a raw vector leaked in
