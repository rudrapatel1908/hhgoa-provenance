"""
Tests the CLI's confirmation gate that protects testnet POL from being
spent by an accidental non-dry-run invocation. Mocks pipeline.register
entirely -- this test is only about whether the gate blocks/allows the
call, not about pipeline behavior itself.
"""

from unittest.mock import patch

from src import cli as cli_mod


def _fake_pipeline_result():
    from src.models import EvidenceStatus, PipelineResult
    return PipelineResult(final_status=EvidenceStatus.VERIFIED, stages=[], dry_run=False)


def test_dry_run_never_prompts(tmp_path, capsys, monkeypatch):
    """--dry-run must never hit the confirmation gate at all."""
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(
        AssertionError("input() should not be called for --dry-run")
    ))
    with patch.object(cli_mod, "register", return_value=_fake_pipeline_result()):
        cli_mod.main([
            "register", "--image", "x.jpg", "--url", "https://example.com",
            "--dry-run", "--out", str(tmp_path),
        ])
    # no assertion error raised means input() was never called


def test_yes_flag_skips_prompt(tmp_path, monkeypatch):
    """--yes must skip the confirmation gate for a real (non-dry-run) call."""
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(
        AssertionError("input() should not be called when --yes is passed")
    ))
    with patch.object(cli_mod, "register", return_value=_fake_pipeline_result()):
        cli_mod.main([
            "register", "--image", "x.jpg", "--url", "https://example.com",
            "--yes", "--out", str(tmp_path),
        ])


def test_real_registration_without_yes_requires_typed_confirmation(tmp_path, monkeypatch):
    """A real registration without --yes must prompt, and abort (never
    calling the pipeline) if the user doesn't type exactly 'confirm'."""
    monkeypatch.setattr("builtins.input", lambda *_: "not confirm")
    with patch.object(cli_mod, "register") as mock_register:
        exit_code = cli_mod.main([
            "register", "--image", "x.jpg", "--url", "https://example.com",
            "--out", str(tmp_path),
        ])
    mock_register.assert_not_called()
    assert exit_code == 1


def test_real_registration_proceeds_on_typed_confirm(tmp_path, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: "confirm")
    with patch.object(cli_mod, "register", return_value=_fake_pipeline_result()) as mock_register:
        cli_mod.main([
            "register", "--image", "x.jpg", "--url", "https://example.com",
            "--out", str(tmp_path),
        ])
    mock_register.assert_called_once()
