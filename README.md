# HH Goa Provenance Engine

Media provenance verification: face correspondence + genuine live
reverse-image search + cryptographic commitment anchored on Polygon
Amoy. Built for Hacker House Goa 2026, Task 3.

Backend/CLI only — no frontend.

## 1. Overview

Given an input image and a claimed public source URL, this system
answers one question as honestly as the evidence allows:

> *Is the face in this image consistent with the face at this publicly
> claimed source, and was that source independently discoverable by a
> live reverse-image search — enough to justify committing a
> tamper-evident record to a public blockchain?*

It does **not** claim to prove a person's real-world legal identity,
physical presence, or "% match" certainty. It reports concrete,
falsifiable evidence: a face distance under a documented threshold, a
URL independently rediscovered by search, and a cryptographic digest
you can re-verify yourself against chain state at any time.

## 2. Key idea: the hybrid architecture

A user-supplied URL alone proves nothing — it's just a claim. A
reverse-image search alone can be gamed by picking whichever result is
convenient. This system requires **both**, computed independently, to
agree:

```
claimed source verification  +  independent reverse-search corroboration
                    +  face correspondence
                    +  cryptographic provenance
                    +  blockchain verification
```

The claimed URL is canonicalized and compared against candidates
returned by a live SerpApi Google Lens search of the **original input
photo** — the same search `discover` uses, not a search of the claimed
source's own image. This is a deliberate design choice, not an
implementation detail: searching the source's own image only proves the
source itself is independently indexed, whereas searching the original
input photo proves something stronger and more directly on-point —
starting from nothing but the photo, live search independently arrives
at this exact claimed URL. That's the literal shape of the Task 3
requirement (face scan → web search → matching post), and it means
`register`'s corroboration check is held to the same evidentiary
standard as `discover`'s. Only if the claimed URL is *rediscovered* in
that independent result set does evidence reach `CORROBORATED`.

## 3. Architecture

```
                 USER INPUT
          ┌─────────────────────┐
          │ Input image         │
          │ Claimed public URL  │
          └──────────┬──────────┘
                     │
             ┌───────┴────────┐
             ▼                ▼
      FACE ANALYSIS       SOURCE ANALYSIS
             │            (fetch, canonicalize,
             │             extract og:image)
             └───────┬────────┘
                     ▼
              FACE CORRESPONDENCE
                     │
                     ▼
             GENUINE LIVE SEARCH  (SerpApi / Google Lens)
                     │
                     ▼
          CLAIMED SOURCE REDISCOVERED?
             ┌───────┴───────┐
            NO              YES
             │               │
        VERIFIED        CORROBORATED
        (no search             │
         corroboration)        ▼
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

## 4. Threat model

**Protects against:**
- A claimed source that was never independently corroborated being
  reported as strongly verified (gated at `CORROBORATED`, not below).
- Post-hoc tampering with the local manifest file — any single-byte
  change produces a different SHA-256, and `audit` mode will report
  `TAMPER_DETECTED` because the re-hashed local digest no longer
  matches the immutable on-chain digest.
- False "verified" output from a failed/reverted transaction — the
  pipeline never advances past `CORROBORATED` unless a receipt with
  `status == 1` is observed AND a separate read-only call confirms the
  digest on-chain.
- Silent first-face selection on ambiguous multi-face images.

**Does NOT protect against:**
- A source page itself being fraudulent or a deepfake (the system
  checks *consistency*, not ground truth about the real world).
- A search provider's index gaps — if SerpApi hasn't indexed a
  legitimate source yet, corroboration will correctly fail to reach
  `CORROBORATED` even though the source is genuine (reported as
  `VERIFIED`, not `REJECTED`, to reflect that distinction).
- Coordinated manipulation of the reverse-search provider's own index.
- Someone with the deployer's private key registering false records —
  the chain only proves *that a hash was committed by that address at
  that time*, not that the underlying evidence was correct.

## 5. Privacy model

- Scope is intentionally limited to **public, authorized material**:
  public figures, public posts, Creative Commons/public-domain media,
  or images you have explicit permission to verify. The system does
  not scrape private accounts or bypass access controls, robots
  restrictions, or paywalls.
- Raw face embeddings **never** leave the process boundary they're
  computed in and are **never** written to the manifest or the chain —
  only `embedding_sha256` (a one-way hash) is stored.
- The blockchain stores a 32-byte digest, a submitter address, a
  timestamp, and an optional IPFS URI — nothing else. No images, no
  biometric vectors, no JSON.
- This is not, and must not become, a public biometric database.

## 6. Setup

Recommended interpreter: **Python 3.11** (best current wheel
availability for `dlib`; 3.12 works on most platforms but check before
relying on it).

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`dlib` builds from source on some platforms if no wheel is available —
ensure `cmake` and a C++ compiler toolchain are installed first
(`sudo apt install cmake build-essential` on Debian/Ubuntu, or
`brew install cmake` on macOS).

```bash
cp .env.example .env
# edit .env with your real values
```

## 7. Search API setup (SerpApi)

1. Create an account at serpapi.com and copy your API key.
2. Set `SERPAPI_API_KEY` in `.env`.
3. This project uses SerpApi's `engine=google_lens` endpoint, which
   requires the query image be reachable via a public URL (it searches
   the claimed source's extracted image, not raw uploaded bytes for
   this engine). See "Known limitations" for what this means if your
   input image itself isn't hosted anywhere.

## 8. Polygon Amoy setup

- Chain ID: `80002`
- Public RPC: use a provider such as Alchemy, Infura, or the public
  Amoy RPC endpoint — set `POLYGON_AMOY_RPC_URL`.
- Faucet: fund a **testnet-only** wallet via the official Polygon
  faucet (search "Polygon Amoy faucet" — the exact URL changes
  periodically, so use the one documented at polygon.technology at the
  time you deploy).
- Set `PRIVATE_KEY` to that testnet wallet's private key. **Never** use
  a wallet that holds real funds.
- `EXPLORER_BASE_URL` defaults to `https://amoy.polygonscan.com/tx/`.

## 9. Remix deployment

1. Open remix.ethereum.org.
2. Create `FaceVerificationRegistry.sol` and paste the contents of
   `contracts/FaceVerificationRegistry.sol`.
3. Compile with Solidity `^0.8.24` (Solidity compiler tab).
4. In the "Deploy & Run Transactions" tab, set Environment to
   "Injected Provider – MetaMask" and switch MetaMask to Polygon Amoy
   (chain ID 80002).
5. Deploy. Confirm the transaction in MetaMask.
6. Copy the deployed contract address into `.env` as
   `CONTRACT_ADDRESS`.
7. The ABI shipped in this repo (`contracts/FaceVerificationRegistry.abi.json`)
   is **generated directly from the Solidity source by the real `solc`
   compiler**, not hand-written — run `python scripts/compile_contract.py`
   any time you change the contract to regenerate it (see
   `contracts/COMPILATION.md` for the exact compiler version used). The
   ABI's function/event/error signatures are unaffected by optimizer
   settings, so this file is valid regardless of what optimizer runs
   Remix used for your deployment, as long as the source is unchanged.
   If you ever do want to cross-check against Remix's own compiled ABI,
   it's under the compiler tab's "Compilation Details" after compiling.

There is no default contract address in this repository — the
placeholder in `.env.example` must be filled in after your own
deployment.

## 10. Running

### Discovery mode (primary Task 3 flow — image only)

```bash
python -m src.cli discover --image examples/positive.jpg
```

Takes **only an image** — no claimed URL. It uploads the image to SerpApi's
real, documented Image API (`POST /image` → `image_id`, JPG/PNG/WebP,
500 KB max, `image_id` expires after 10 minutes), searches with that
`image_id` via Google Lens, filters results down to actual social-media
platforms (`x.com`, `instagram.com`, `linkedin.com`, `youtube.com`,
`facebook.com`, `threads.net`, `tiktok.com` — Wikipedia, news sites, and
blogs are deliberately excluded, since they don't satisfy the "matching
social-media post" requirement even though they're valid provenance
sources), then validates candidates in rank order — fetching each one,
extracting its image, and running a real face comparison — until it finds
one that passes, or exhausts the top candidates. It **never sends a
blockchain transaction.**

### Registration mode (claimed-URL verification + optional blockchain)

```bash
python -m src.cli register \
  --image examples/positive.jpg \
  --url "https://x.com/someone/status/1234567890"
```

A real (non-dry-run) registration spends testnet POL, so it prompts for
typed confirmation before sending anything:

```
This will send a REAL transaction on Polygon Amoy and spend testnet POL.
Type "confirm" to proceed, or anything else to abort:
```

Pass `--yes` to skip this prompt (e.g. for scripting), but never use `--yes`
casually during rehearsal -- use `--dry-run` for that instead, which never
reaches this gate at all and never touches the chain.

### How discovery and registration fit together

These are two different, complementary flows — not one replacing the
other:

- **`discover`**: proves the search requirement can run on an image alone,
  with no human-supplied answer. Entirely off-chain.
- **`register`**: takes a specific claimed source (which can be the URL
  `discover` just found) and produces the deterministic, hashable,
  on-chain-anchorable provenance record.

A natural demo flow is `discover` → take its matched URL → feed it into
`register --dry-run` → confirm `CORROBORATED` → then a real `register` run.

Dry run (stops before any blockchain transaction; does not claim
on-chain confirmation):

```bash
python -m src.cli register \
  --image examples/positive.jpg \
  --url "https://x.com/someone/status/1234567890" \
  --dry-run
```

## 11. Pre-flight check, audit, and tamper detection

Before any real transaction, confirm your RPC/wallet/ABI/contract wiring
is correct with a purely read-only check:

```bash
python -m src.cli check-config
```

This never sends a transaction — it connects, derives your wallet
address, and makes one read-only contract call to confirm the ABI and
contract address round-trip correctly.

```bash
python -m src.cli audit --manifest proof/manifest.json
```

`audit` compares the manifest **as it currently exists on disk** against
the hash that was *actually registered* on-chain (read from the sibling
`verification.json`, not re-derived from the current manifest — this
distinction matters, see below). Possible results:

- `NOT_REGISTERED` — no real registration has happened for this manifest
  yet (e.g. it came from a `--dry-run`)
- `ON_CHAIN_VERIFIED` — current manifest hash matches what's on-chain
- `TAMPER_DETECTED` — current manifest hash does **not** match what was
  registered — the file was modified after registration
- `REGISTERED_HASH_NOT_FOUND_ON_CHAIN` — an inconsistency worth
  investigating (verification.json claims a registration the chain
  doesn't actually have)

**Why audit reads verification.json instead of just re-hashing the
manifest and looking that up on-chain:** the contract stores records in
a mapping keyed by hash. If you re-hash a *tampered* manifest and look
up that new hash, the lookup correctly returns "not found" — a tampered
manifest hashes to a value that was never registered under that key.
That is not the same thing as "found, but mismatched." `audit` instead
looks up the *originally registered* hash and compares it against the
manifest's current hash — that comparison is what actually detects
tampering.

Tamper-demo walkthrough (only meaningful after a real registration —
before that, every audit correctly reports `NOT_REGISTERED`):
```bash
# 1. Register for real -> proof/manifest.json + verification.json written
python -m src.cli audit --manifest proof/manifest.json     # ON_CHAIN_VERIFIED

# 2. Hand-edit any field in proof/manifest.json (e.g. claimed_source.title)
python -m src.cli audit --manifest proof/manifest.json     # TAMPER_DETECTED

# 3. Restore the original file (e.g. from git or your proof/ backup)
python -m src.cli audit --manifest proof/manifest.json     # ON_CHAIN_VERIFIED again
```

## 12. Testing

```bash
pip install -r requirements.txt
pytest tests/ -v
```

All external services (SerpApi, Pinata, Polygon RPC) are mocked in
unit tests — no network calls or credentials required to run the
suite. The live demo path itself is never mocked.

## 12a. Local API (for a UI layer)

A thin FastAPI adapter (`src/api.py`) exposes the same backend functions
the CLI uses — no duplicated logic, same source of truth either way.
Localhost only; never deployed publicly.

```bash
uvicorn src.api:app --reload --port 8000
```

Endpoints:

| Endpoint | Method | Blockchain? |
|---|---|---|
| `/api/health` | GET | no |
| `/api/check-config` | GET | read-only |
| `/api/discover` | POST (multipart image) | no |
| `/api/verify` | POST (multipart image + url) | **always dry-run — hardcoded, not a flag** |
| `/api/register` | POST (multipart image + url + `confirm`) | real write, but only if `confirm` is the exact literal string `"REGISTER"` |
| `/api/audit` | GET (`?manifest=path`) | read-only |

`/api/verify` and `/api/register` are separate endpoints on purpose,
not one endpoint with a dry-run flag — a frontend bug that sends the
wrong boolean can flip a flag, but it can't accidentally call a
different endpoint. `/api/register` additionally requires an exact
confirmation string as a second, independent gate beyond whatever
"explicit click" UX a frontend adds — a defense-in-depth measure given
how little testnet POL is left for the actual demo.

## 13. Demo walkthrough

Screen recording should show, in order:
1. The input image and the claimed URL in the terminal command.
2. `[01]`–`[04]`: input validation, face analysis, source fetch, face
   correspondence, all passing with real computed values (SHA-256,
   face distance).
3. `[05]`–`[07]`: the live SerpApi call executing, a non-trivial
   candidate count, and the claimed URL being flagged as
   independently rediscovered.
4. `[08]`–`[09]`: manifest hash and (if configured) IPFS CID.
5. `[10]`–`[12]`: the real Polygon Amoy transaction hash, receipt
   confirmation, and the independent on-chain read matching the local
   hash.
6. The final `PROVENANCE VERIFIED` panel.
7. Optionally, the tamper-detection walkthrough from section 11.

## 14. Known limitations

- **Discovery upload constraints**: SerpApi's Image API caps uploads at
  500 KB, JPG/PNG/WebP only, and the resulting `image_id` expires after
  10 minutes — `discover` fails closed with a clear error rather than
  silently resizing/re-encoding your original file if it's too large.
- **Discovery only searches indexed social platforms**: if a person's
  only public presence is on a platform outside the allowlist (or their
  post predates Google's index), `discover` will correctly return
  `NO_MATCH` rather than falling back to a non-social source.
- **Search-provider indexing**: a genuine, legitimate source that
  SerpApi/Google Lens hasn't indexed yet will not reach
  `CORROBORATED` — it will correctly stop at `VERIFIED`. This is a
  provider limitation, not a system bug.
- **API rate limits**: SerpApi and Pinata both have plan-based rate
  limits; heavy demo rehearsal can exhaust a free-tier quota.
- **Source pages changing or being deleted**: if the claimed post is
  edited or removed between demo runs, `SOURCE_FETCH` will fail and
  the pipeline will correctly return `REJECTED`.
- **Face detection failures**: low light, extreme angles, heavy
  occlusion, or very small faces (<60px bounding box) will fail
  quality checks by design.
- **Multiple faces**: the default policy rejects images with more
  than one detected face rather than guessing which one is intended.
- **Crops/severe compression**: face embeddings are robust to
  moderate recompression and cropping but not guaranteed across
  extreme transformations; the configured `FACE_DISTANCE_THRESHOLD`
  determines the tolerance.
- **The Google Lens engine's URL requirement**: this SerpApi engine
  searches a *reachable image URL*, not raw uploaded bytes. In this
  pipeline the searched image is the claimed source's extracted
  `og:image` (already a public URL), not the local input file — so
  the "genuine live search" step corroborates the *source*, which is
  the design intent, but does not independently reverse-search the
  raw input file itself. If SerpApi's supported request shape changes,
  update `src/search.py` only — it's isolated for exactly this reason.
- **RPC outages**: `POLYGON_AMOY_RPC_URL` availability is a hard
  external dependency; a failed connection surfaces as a clear
  `ConfigError`/`TransactionFailed`, not a silent skip.
- **IPFS outages**: pinning failures are non-fatal by policy — the
  chain registration proceeds with an empty `manifestURI` rather than
  blocking on IPFS availability.

## 15. Project structure

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
├── examples/
├── proof/              generated manifest.json / verification.json
├── .env.example
├── requirements.txt
└── README.md
```

## Manifest verification policy

Every manifest embeds a `verification.policy` block recording exactly which
rules were applied to reach its status (single-face requirement, source
access requirement, face-match requirement, whether search corroboration
was required, and a policy version string). This makes each provenance
record self-describing — an auditor doesn't need to read source code to
know what a given `CORROBORATED` or `VERIFIED` status actually required.

The `manifest.search` block also separately reports `exact_match_count`
and `visual_match_count` from SerpApi's response, rather than collapsing
them into one number — SerpApi marks some visual matches as pixel-exact
via a per-result flag, which is read from the single search response
already made (no second API call, no extra quota spent).

## Checklist

```
[x] genuine live reverse search (SerpApi, isolated provider module)
[x] supplied source verification (fetch + canonicalize + extract)
[x] source independently rediscovered (URL equivalence against search)
[x] face detection (face_recognition, pretrained)
[x] face embedding (128-d, pretrained)
[x] face correspondence (distance vs. configurable threshold)
[x] no custom model training
[x] no hardcoded result / no input->person dictionary
[x] deterministic canonical manifest (sorted-key JSON)
[x] SHA-256 digest, distinguished from any derived image hash
[x] raw embedding NOT on-chain (only embedding_sha256)
[x] IPFS support (Pinata, non-blocking failure)
[x] Polygon Amoy support (chain id 80002)
[x] real transaction (web3.py sign/send)
[x] receipt confirmation (status==1 required before advancing)
[x] read-only on-chain verification (separate call from register)
[x] tamper detection (audit mode re-hashes + re-queries)
[x] negative case (face mismatch / unreachable source -> REJECTED)
[x] error handling (timeouts, retries not infinite, clear exceptions)
[x] tests (manifest, URL norm, search parsing, face policy, evidence, chain)
[x] README (this file)
[x] Remix deployment guide (section 9)
[x] demo instructions (section 13)
```
