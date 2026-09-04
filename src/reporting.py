"""Rich terminal reporting. Every value shown is read from PipelineResult
-- nothing here is hardcoded or invented for display purposes."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import EvidenceStatus, PipelineResult, StageStatus

console = Console()

_STATUS_GLYPH = {
    StageStatus.PASS: "[bold green]\u2713 PASS[/bold green]",
    StageStatus.FAIL: "[bold red]\u2717 FAIL[/bold red]",
    StageStatus.SKIPPED: "[yellow]\u2013 SKIPPED[/yellow]",
}

_FINAL_STYLE = {
    EvidenceStatus.REJECTED: ("red", "REJECTED"),
    EvidenceStatus.CLAIMED: ("yellow", "CLAIMED"),
    EvidenceStatus.VERIFIED: ("cyan", "VERIFIED"),
    EvidenceStatus.CORROBORATED: ("blue", "CORROBORATED"),
    EvidenceStatus.ON_CHAIN_VERIFIED: ("bold green", "PROVENANCE VERIFIED \u2713"),
    EvidenceStatus.TAMPER_DETECTED: ("bold red", "TAMPER DETECTED"),
}


def print_header():
    console.print(Panel.fit("HH GOA MEDIA PROVENANCE ENGINE", style="bold white on blue"))


def print_discovery_header():
    console.print(Panel.fit("HH GOA MEDIA DISCOVERY ENGINE", style="bold white on blue"))


def print_discovery_result(result):
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=3)
    table.add_column("Stage")
    table.add_column("Status")
    table.add_column("Detail")

    for i, stage in enumerate(result.stages, start=1):
        detail = stage.error if stage.error else stage.detail
        table.add_row(
            f"{i:02d}", stage.stage, _STATUS_GLYPH.get(stage.status, str(stage.status)),
            f"{detail}  ({stage.duration_ms:.0f}ms)",
        )
    console.print(table)

    if result.match:
        m = result.match
        console.print()
        console.print("[bold]MATCHING SOCIAL-MEDIA POST[/bold]")
        console.print("─" * 48)
        console.print(f"Platform:       {m.platform}")
        console.print(f"URL:            {m.candidate.url}")
        console.print(f"Match type:     {'exact' if m.candidate.is_exact_match else 'visual'}")
        console.print(f"Candidate rank: #{m.candidate_rank + 1}")
        console.print(f"Face distance:  {m.face_comparison.distance:.4f} (threshold {m.face_comparison.threshold})")
        console.print()
        console.print(Panel.fit("MATCHING POST FOUND \u2713", style="bold green"))
    elif result.final_status.value == "no_match":
        console.print()
        console.print(
            f"[yellow]{result.social_candidate_count} social candidate(s) checked, "
            f"none passed source access + face correspondence.[/yellow]"
        )
        console.print(Panel.fit("NO MATCH FOUND", style="bold yellow"))
    else:
        console.print(Panel.fit("DISCOVERY REJECTED", style="bold red"))


def print_result(result: PipelineResult):
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", width=3)
    table.add_column("Stage")
    table.add_column("Status")
    table.add_column("Detail")

    for i, stage in enumerate(result.stages, start=1):
        detail = stage.error if stage.error else stage.detail
        table.add_row(
            f"{i:02d}", stage.stage, _STATUS_GLYPH.get(stage.status, str(stage.status)),
            f"{detail}  ({stage.duration_ms:.0f}ms)",
        )

    console.print(table)

    if result.manifest_hash_hex:
        console.print(f"[bold]Manifest SHA-256:[/bold] {result.manifest_hash_hex}")
    if result.ipfs_cid:
        console.print(f"[bold]IPFS CID:[/bold] {result.ipfs_cid}")
    if result.blockchain:
        console.print(f"[bold]Transaction:[/bold] {result.blockchain.tx_hash}")
        console.print(f"[bold]Block:[/bold] {result.blockchain.block_number}")
    if result.onchain_verification:
        console.print(f"[bold]On-chain hash:[/bold] {result.onchain_verification.onchain_hash_hex}")
        console.print(f"[bold]Hashes match:[/bold] {result.onchain_verification.hashes_match}")
    if result.dry_run:
        console.print("[yellow]DRY RUN -- no transaction was sent, no on-chain claim made.[/yellow]")

    style, label = _FINAL_STYLE[result.final_status]
    console.print(Panel.fit(label, style=f"bold {style}" if "bold" not in style else style))


def print_audit(audit_result: dict):
    table = Table(show_header=False)
    for k, v in audit_result.items():
        table.add_row(str(k), str(v))
    console.print(table)

    status = audit_result["status"]
    color = {
        "ON_CHAIN_VERIFIED": "bold green",
        "TAMPER_DETECTED": "bold red",
        "NOT_REGISTERED": "yellow",
        "REGISTERED_HASH_NOT_FOUND_ON_CHAIN": "bold red",
    }.get(status, "yellow")
    console.print(Panel.fit(status, style=color))
