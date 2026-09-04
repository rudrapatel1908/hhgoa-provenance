"""
Regenerates contracts/FaceVerificationRegistry.abi.json directly from the
Solidity source using the real solc compiler -- never hand-edit the ABI
file. This removes the single biggest risk in the whole pipeline: an ABI
that has silently drifted from the deployed contract's actual interface.

Usage:
    python scripts/compile_contract.py

Requires `solc` on PATH (or set SOLC_BINARY env var to its path). Get a
matching version from https://github.com/ethereum/solidity/releases --
use the same major.minor as the `pragma solidity` line in the .sol file.

Note: the ABI (function/event/error signatures) is NOT affected by
optimizer settings -- only bytecode is. So this ABI is valid regardless
of what optimizer runs Remix used when you deployed, as long as the
source file matches exactly.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
CONTRACT = ROOT / "contracts" / "FaceVerificationRegistry.sol"
ABI_OUT = ROOT / "contracts" / "FaceVerificationRegistry.abi.json"
COMPILATION_NOTES = ROOT / "contracts" / "COMPILATION.md"


def find_solc() -> str:
    solc = os.environ.get("SOLC_BINARY", "solc")
    try:
        result = subprocess.run([solc, "--version"], capture_output=True, text=True, check=True)
        return solc, result.stdout
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: could not run '{solc} --version': {exc}", file=sys.stderr)
        print("Install solc from https://github.com/ethereum/solidity/releases "
              "or set SOLC_BINARY to its path.", file=sys.stderr)
        sys.exit(1)


def compile_and_extract_abi(solc: str) -> list:
    out_dir = ROOT / "build" / "solc_out"
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [solc, "--abi", "--optimize", str(CONTRACT), "-o", str(out_dir), "--overwrite"],
        check=True,
    )
    abi_file = out_dir / "FaceVerificationRegistry.abi"
    with open(abi_file) as f:
        return json.load(f)


def main():
    solc, version_output = find_solc()
    abi = compile_and_extract_abi(solc)

    with open(ABI_OUT, "w") as f:
        json.dump(abi, f, indent=2)
        f.write("\n")

    version_line = version_output.strip().splitlines()[-1]
    with open(COMPILATION_NOTES, "w") as f:
        f.write(
            "# Compilation provenance\n\n"
            f"ABI in `FaceVerificationRegistry.abi.json` was generated directly from\n"
            f"`FaceVerificationRegistry.sol` by `scripts/compile_contract.py`.\n\n"
            f"Compiler: {version_line}\n\n"
            "Do not hand-edit the ABI file. If you change the contract source,\n"
            "re-run `python scripts/compile_contract.py` to regenerate it.\n\n"
            "The ABI (function/event/error signatures) is independent of optimizer\n"
            "settings -- only bytecode changes with those. This ABI is therefore\n"
            "valid for any deployment of this exact source, including ones made\n"
            "through Remix with different optimizer settings.\n"
        )

    print(f"Wrote {ABI_OUT}")
    print(f"Wrote {COMPILATION_NOTES}")
    print(f"Compiler: {version_line}")


if __name__ == "__main__":
    main()
