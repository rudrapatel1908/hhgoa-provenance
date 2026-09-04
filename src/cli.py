"""
CLI entrypoint.

    python -m src.cli register --image examples/input.jpg --url "https://..."
    python -m src.cli register --image examples/input.jpg --url "https://..." --dry-run
    python -m src.cli audit --manifest proof/manifest.json
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import reporting
from .pipeline import PipelineConfig, audit, discover, register


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hhgoa-provenance")
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    disc = sub.add_parser("discover", help="find a matching public social-media post from an image alone")
    disc.add_argument("--image", required=True, help="path to the input image")
    disc.add_argument("--max-results", type=int, default=None, help="override MAX_SEARCH_RESULTS")

    reg = sub.add_parser("register", help="run the full provenance pipeline")
    reg.add_argument("--image", required=True, help="path to the input image")
    reg.add_argument("--url", required=True, help="claimed public source URL")
    reg.add_argument("--dry-run", action="store_true", help="stop before blockchain registration")
    reg.add_argument("--no-ipfs", action="store_true", help="skip IPFS pinning even if configured")
    reg.add_argument("--out", default="proof", help="output directory for the proof bundle")
    reg.add_argument(
        "--yes", action="store_true",
        help="skip the interactive confirmation before a real (non-dry-run) blockchain "
             "transaction. Without this flag, a real registration will prompt for typed "
             "confirmation so testnet POL is never spent by accident.",
    )

    aud = sub.add_parser("audit", help="re-hash a manifest and check it against on-chain state")
    aud.add_argument("--manifest", required=True, help="path to a manifest.json")

    chk = sub.add_parser(
        "check-config",
        help="read-only pre-flight check: confirms RPC connects, wallet derives, "
             "ABI loads, and the configured contract address is reachable. "
             "Never sends a transaction.",
    )

    return parser


def _write_proof_bundle(out_dir: str, result) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if result.manifest:
        with open(out / "manifest.json", "w") as f:
            json.dump(dataclasses.asdict(result.manifest), f, indent=2)

    verification = {
        "final_status": result.final_status.value,
        "local_manifest_hash": result.manifest_hash_hex,
        "onchain_manifest_hash": result.onchain_verification.onchain_hash_hex if result.onchain_verification else None,
        "contract_address": result.blockchain.contract_address if result.blockchain else None,
        "transaction_hash": result.blockchain.tx_hash if result.blockchain else None,
        "block_number": result.blockchain.block_number if result.blockchain else None,
        "dry_run": result.dry_run,
    }
    with open(out / "verification.json", "w") as f:
        json.dump(verification, f, indent=2)

    # summary.json: a compact, human-readable audit summary -- the file
    # a judge or reviewer should open first, without needing to parse the
    # full manifest or verification.json.
    summary = {
        "status": result.final_status.value,
        "manifest_hash": result.manifest_hash_hex,
        "transaction_hash": result.blockchain.tx_hash if result.blockchain else None,
        "contract_address": result.blockchain.contract_address if result.blockchain else None,
        "chain_id": os.environ.get("CHAIN_ID"),
        "claimed_source_url": result.manifest.claimed_source.url if result.manifest else None,
        "search_corroboration": (
            result.manifest.search.claimed_source_rediscovered if result.manifest else None
        ),
        "dry_run": result.dry_run,
    }
    with open(out / "summary.json", "w") as f:
        json.dump(summary, f, indent=2)


def main(argv=None) -> int:
    load_dotenv()
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "discover":
        reporting.print_discovery_header()
        config = PipelineConfig()
        if args.max_results:
            config.max_search_results = args.max_results
        result = discover(image_path=args.image, config=config)
        reporting.print_discovery_result(result)
        return 0 if result.final_status.value == "discovered" else 1

    if args.command == "register":
        if args.no_ipfs:
            os.environ.pop("PINATA_JWT", None)

        # POL-protection guard: a real (non-dry-run) registration spends
        # testnet gas. Require explicit, typed confirmation unless --yes
        # was passed, so a real transaction is never sent by accident.
        if not args.dry_run and not args.yes:
            reporting.console.print(
                "[yellow]This will send a REAL transaction on Polygon Amoy and spend "
                "testnet POL.[/yellow]"
            )
            confirmation = input('Type "confirm" to proceed, or anything else to abort: ')
            if confirmation.strip().lower() != "confirm":
                reporting.console.print("[red]Aborted -- no transaction sent.[/red]")
                return 1

        reporting.print_header()
        result = register(
            image_path=args.image, claimed_url=args.url,
            config=PipelineConfig(), dry_run=args.dry_run,
        )
        reporting.print_result(result)
        _write_proof_bundle(args.out, result)
        return 0 if result.final_status.value != "rejected" else 1

    if args.command == "audit":
        result = audit(args.manifest)
        reporting.print_audit(result)
        return 0 if result["status"] == "ON_CHAIN_VERIFIED" else 1

    if args.command == "check-config":
        from .pipeline import check_config
        result = check_config()
        if not result["ok"]:
            reporting.console.print(f"[bold red]{result['error']}[/bold red]")
            return 1
        reporting.console.print(f"[bold green]RPC connected:[/bold green] {result['rpc_url']}")
        reporting.console.print(f"[bold green]Wallet:[/bold green] {result['wallet']}")
        reporting.console.print(f"[bold green]Contract reachable:[/bold green] {result['contract_address']}")
        reporting.console.print(f"[bold green]Chain ID:[/bold green] {result['chain_id']}")
        reporting.console.print("[bold green]No transaction sent -- read-only check only.[/bold green]")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
