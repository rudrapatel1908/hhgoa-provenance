# 🔗 HH Goa Provenance Engine

**Does this photo actually belong to that public post — and can I prove it, permanently?**

A media provenance pipeline that combines face correspondence, a genuine
live reverse-image search, and cryptographic anchoring on Polygon Amoy.
Built for Hacker House Goa 2026, Task 3.

`Python 3.11` · `face_recognition / dlib` · `SerpApi Google Lens` · `web3.py` · `Solidity ^0.8.24` · `Polygon Amoy (80002)`

Backend / CLI only — no frontend.

---

## Why this exists

A claimed URL alone proves nothing — it's just a claim. A reverse-image
search alone can be gamed by cherry-picking whichever result is
convenient. So this system requires **both**, computed independently,
to agree before it will call anything "corroborated":

```
claimed source verification  +  independent reverse-search corroboration
                    +  face correspondence
                    +  cryptographic manifest
                    +  on-chain anchoring
```

The claimed URL is checked against candidates from a live SerpApi
Google Lens search of the **original input photo** — the same search
`discover` uses, not a search of the claimed source's own image. That's
a deliberate choice: only if a claimed source is *independently
rediscovered*, starting from nothing but the photo, does evidence reach
`CORROBORATED`.

---

## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SerpApi key, RPC URL, testnet wallet key

# 1. Find a matching public post from an image alone (no chain, no cost)
python -m src.cli discover --image examples/positive.jpg

# 2. Verify a specific claimed URL, without spending anything
python -m src.cli register --image examples/positive.jpg \
  --url "https://x.com/someone/status/1234567890" --dry-run

# 3. Confirm your RPC/wallet/contract wiring, read-only
python -m src.cli check-config

# 4. Go on-chain for real
python -m src.cli register --image examples/positive.jpg \
  --url "https://x.com/someone/status/1234567890"
```

---

## A real run, end to end

This isn't a projected benchmark — it's one actual `register` run against
Polygon Amoy, numbers pulled straight from the pipeline's own stage timing
and the resulting transaction receipt.

| Stage | Result |
|---|---|
| Face analysis | 1 face detected, quality `pass` |
| Face correspondence | distance `0.0996` (threshold `0.6`) |
| Live search (SerpApi / Google Lens) | 20 visual matches, claimed source rediscovered at rank #1 |
| Manifest hash | `0x2e42f58e...6c6ec9fc` (SHA-256) |
| On-chain transaction | [`0x5c2e0849...4c73089a`](https://amoy.polygonscan.com/tx/0x5c2e0849ef785db0c922a08441ba5c1a518775580031e5e8822d563a4c73089a) — block `46639561` |
| Real cost | `0.00243 POL` at `30 gwei` |
| Independent on-chain re-check | local digest == on-chain digest → `ON_CHAIN_VERIFIED` |

Every one of those fields is independently checkable on
[Polygonscan](https://amoy.polygonscan.com) — this repo doesn't ask you to
trust its own output.

---

## Architecture

```
                 USER INPUT
          ┌─────────────────────┐
          │ Input image         │
          │ Claimed public URL  │
          └──────────┬──────────┘
                      │
             ┌────────┴────────┐
             ▼                 ▼
      FACE ANALYSIS      SOURCE ANALYSIS
             │           (fetch, canonicalize,
             │            extract og:image)
             └────────┬────────┘
                      ▼
              FACE CORRESPONDENCE
                      │
                      ▼
        GENUINE LIVE SEARCH (SerpApi / Google Lens)
                      │
                      ▼
          CLAIMED SOURCE REDISCOVERED?
             ┌────────┴────────┐
            NO                YES
             │                 │
        VERIFIED          CORROBORATED
     (no search                │
      corroboration)           ▼
                       CANONICAL MANIFEST → SHA-256
                                │
                    ┌───────────┴───────────┐
                    ▼                       ▼
                  IPFS               Polygon Amoy
               (optional)            registerRecord()
                                          │
                                    receipt confirmed
                                          │
                                  independent verifyRecord()
                                          │
                                   ON_CHAIN_VERIFIED
```

*(Full design rationale, corroboration semantics, and the audit-mode
tamper-detection fix are documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
— optional, add if you want a deep-dive doc separate from this README.)*

---

## What it protects against — and what it doesn't

**Protects against**
- A claimed source that was never independently corroborated being
  reported as strongly verified — gated at `CORROBORATED`, never below.
- Post-hoc tampering with the local manifest: any byte change produces
  a different SHA-256, and `audit` correctly reports `TAMPER_DETECTED`
  by comparing against the *originally registered* hash, not a
  re-derived one.
- False "verified" output from a failed/reverted transaction — nothing
  advances past `CORROBORATED` without a receipt `status == 1` **and**
  a separate read-only on-chain confirmation.
- Silent first-face selection on ambiguous multi-face images.

**Does not protect against**
- A source page itself being fraudulent or a deepfake — this checks
  *consistency*, not real-world ground truth.
- Search-index gaps — a genuine source SerpApi hasn't indexed yet
  correctly stops at `VERIFIED`, not `CORROBORATED`.
- Someone with the deployer's private key registering false records —
  the chain proves *that a hash was committed by that address at that
  time*, not that the underlying evidence was correct.

---

## Privacy model

- Scoped to **public, authorized material** only: public figures,
  public posts, CC/public-domain media, or images you have explicit
  permission to verify. No scraping of private accounts or bypassing
  access controls.
- Raw face embeddings never leave the process and are never written to
  the manifest or the chain — only a one-way `embedding_sha256`.
- The chain stores a 32-byte digest, submitter address, timestamp, and
  an optional IPFS URI. No images. No biometric vectors. No JSON.

---

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`dlib` builds from source on some platforms — install `cmake` and a C++
toolchain first (`apt install cmake build-essential` / `brew install cmake`).

```bash
cp .env.example .env
# fill in: SERPAPI_API_KEY, POLYGON_AMOY_RPC_URL, CONTRACT_ADDRESS, PRIVATE_KEY
```

**SerpApi** — create an account, set `SERPAPI_API_KEY`. Uses the real
`engine=google_lens` endpoint against the claimed source's `og:image`.

**Polygon Amoy** — chain ID `80002`. Get an RPC URL (Alchemy/Infura/public
endpoint), fund a **testnet-only** wallet from the official Polygon
faucet, set `PRIVATE_KEY`. Never use a wallet holding real funds.

**Deploying the contract** — open [Remix](https://remix.ethereum.org),
paste `contracts/FaceVerificationRegistry.sol`, compile with Solidity
`^0.8.24`, deploy via Injected Provider on Amoy, copy the address into
`CONTRACT_ADDRESS`. The shipped ABI (`contracts/FaceVerificationRegistry.abi.json`)
is generated directly from source by `solc` via `scripts/compile_contract.py`
— not hand-written.

---

## Commands

| Command | What it does | Touches the chain? |
|---|---|---|
| `discover --image <path>` | Image → matching social post, no claimed URL needed | Never |
| `register --image <path> --url <url> --dry-run` | Full pipeline, stops before any transaction | Never |
| `register --image <path> --url <url>` | Full pipeline + real on-chain registration (prompts for confirmation) | Yes |
| `check-config` | Confirms RPC/wallet/ABI/contract wiring | Never |
| `audit --manifest <path>` | Compares a manifest against what's actually registered on-chain; detects tampering | Read-only |

A natural demo flow: `discover` → feed its matched URL into
`register --dry-run` → confirm `CORROBORATED` → real `register`.

---

## Tamper detection, demonstrated

```bash
# after a real registration:
python -m src.cli audit --manifest proof/manifest.json     # ON_CHAIN_VERIFIED

# hand-edit any field in proof/manifest.json, then:
python -m src.cli audit --manifest proof/manifest.json     # TAMPER_DETECTED

# restore the original file:
python -m src.cli audit --manifest proof/manifest.json     # ON_CHAIN_VERIFIED again
```

`audit` compares the manifest's current hash against the hash that was
*actually registered* (read from `verification.json`), not one
re-derived from the possibly-tampered file — re-hashing a tampered
manifest and looking that new hash up on-chain would just return "not
found," not "found but mismatched."

---

## Testing

```bash
pytest tests/ -v
```

All external services (SerpApi, Pinata, Polygon RPC) are mocked in
unit tests — no network calls or credentials required. The live demo
path itself is never mocked.

---

## Known limitations

- SerpApi's Image API caps uploads at 500 KB (JPG/PNG/WebP); `discover`
  fails closed rather than silently re-encoding oversized files.
- `discover` only searches an allowlist of social platforms — a
  legitimate presence elsewhere correctly returns `NO_MATCH`.
- A genuine source SerpApi hasn't indexed yet correctly stops at
  `VERIFIED`, not `CORROBORATED` — a provider limitation, not a bug.
- SerpApi/Pinata both have plan-based rate limits.
- Low light, extreme angles, heavy occlusion, or faces under ~60px
  fail quality checks by design; multi-face images are rejected rather
  than guessed at.
- RPC/IPFS outages surface as clear errors — IPFS failure is
  non-fatal (registration proceeds with an empty `manifestURI`); RPC
  failure is fatal by design.

---

## Project structure

```
hhgoa-provenance/
├── contracts/
│   ├── FaceVerificationRegistry.sol
│   └── FaceVerificationRegistry.abi.json
├── src/
│   ├── pipeline.py     orchestration / state machine
│   ├── vision.py       face detect, embed, compare
│   ├── source.py       claimed-URL fetch, canonicalize, extract image
│   ├── search.py       SerpApi provider, candidate ranking
│   ├── manifest.py     canonical JSON + SHA-256
│   ├── ipfs.py         Pinata pinning
│   ├── blockchain.py   web3.py tx build/send/verify
│   ├── models.py       typed dataclasses
│   ├── reporting.py    Rich terminal output
│   └── cli.py          entrypoint
├── tests/
├── examples/            demo image instructions (no images shipped)
├── proof/               generated manifest.json / verification.json
├── .env.example
├── requirements.txt
└── README.md
```

---

## Checklist

```
[x] genuine live reverse search (SerpApi, isolated provider module)
[x] supplied source verification (fetch + canonicalize + extract)
[x] source independently rediscovered (URL equivalence against search)
[x] face detection + embedding (face_recognition, pretrained, 128-d)
[x] face correspondence (distance vs. configurable threshold)
[x] no custom model training, no input->person dictionary
[x] deterministic canonical manifest (sorted-key JSON) + SHA-256
[x] raw embedding NOT on-chain (only embedding_sha256)
[x] IPFS support (Pinata, non-blocking failure)
[x] Polygon Amoy support (chain id 80002), real signed transaction
[x] receipt confirmation (status==1 required before advancing)
[x] read-only on-chain verification (separate call from register)
[x] tamper detection (audit re-derives from registered hash, not re-hash+lookup)
[x] negative case (face mismatch / unreachable source -> REJECTED)
[x] tests (manifest, URL norm, search parsing, face policy, evidence, chain)
```