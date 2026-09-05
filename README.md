# 🔗 TRACE — HH Goa Provenance Engine

**Does this photo actually belong to that public post — and can I prove it, permanently?**

A media provenance pipeline combining image-only social-media
discovery, face correspondence, a genuine live reverse-image search,
and cryptographic anchoring on Polygon Amoy. Built for Hacker House Goa
2026, Task 3.

`Python 3.11` · `face_recognition / dlib` · `SerpApi Google Lens` · `web3.py` · `Solidity ^0.8.24` · `Polygon Amoy (80002)` · `FastAPI`

CLI-first, with a local API adapter for an optional UI layer. No public deployment.

---

## Why this exists

Task 3 asks for: face scan → web/social search → matching public post →
blockchain upload → programmatic verification. The naive version of
that is gameable in two obvious ways — a user-supplied URL alone proves
nothing (it's just a claim), and a reverse-image search alone can be
gamed by cherry-picking whichever result is convenient. So this system
has **two entry points that both have to hold up independently**:

```
image-only discovery  +  claimed-source verification
        (no URL given)      (independent search corroboration)
                    +  face correspondence
                    +  cryptographic manifest
                    +  on-chain anchoring
```

**`discover`** takes only an image — no URL — uploads it to SerpApi's
Google Lens, filters results down to actual social-media platforms
(Wikipedia, news, blogs don't count), and validates candidates in rank
order until one's face genuinely matches. **`register`** takes a
claimed URL and independently searches the *original input photo*
(the same mechanism `discover` uses, not the source's own image) to
check whether that exact URL is rediscovered on its own. Only when a
claimed source is independently rediscovered, starting from nothing
but the photo, does evidence reach `CORROBORATED`.

---

## Quick start

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in SerpApi key, RPC URL, testnet wallet key

# 1. Find a matching public social-media post from an image alone — no URL, no cost
python -m src.cli discover --image examples/positive.jpg

# 2. Verify a specific claimed URL, without spending anything
python -m src.cli register --image examples/positive.jpg \
  --url "https://facebook.com/.../post" --dry-run

# 3. Confirm your RPC/wallet/ABI/contract wiring, read-only
python -m src.cli check-config

# 4. Go on-chain for real (prompts for typed confirmation)
python -m src.cli register --image examples/positive.jpg \
  --url "https://facebook.com/.../post"

# 5. Independently re-verify what's on-chain against the local manifest
python -m src.cli audit --manifest proof/manifest.json
```

---

## A real run, end to end

This is one actual `discover` → `register --dry-run` pass — real SerpApi
calls, real face comparisons, nothing mocked or hardcoded. **The
on-chain step has deliberately not been executed yet** — this project
reserves its remaining testnet POL for one final, intentional
registration, done only after everything upstream of it is proven. So
this table stops at `CORROBORATED`, honestly, rather than showing a
transaction that hasn't happened.

| Stage | Result |
|---|---|
| `discover` — face analysis | 1 face detected |
| `discover` — live search | 59 raw results → 20 visual matches → 2 social-media candidates |
| `discover` — social validation | Facebook post found at candidate rank **#10**, face distance `0.1189` (threshold `0.6`) |
| `register --dry-run` on that URL | independent second search (from the original photo) rediscovers the same URL |
| Evidence decision | `CORROBORATED` |
| Manifest hash | `0x0e517b6160...729ac179f0` (SHA-256) |
| Blockchain | not yet executed — reserved for final demo |

Every number above came from an actual terminal run against live
SerpApi results, not a fixture.

---

## Backend pipeline, for judges

Everything in this project runs through the same Python modules,
whether it's invoked from the CLI or the local API adapter — there is
exactly one implementation of the business logic, not two.

```
src/
├── pipeline.py     orchestrates both flows below; owns the state machine
├── vision.py       face detect / quality-check / embed / compare (pretrained, no training)
├── source.py       claimed-URL fetch, canonicalization, og:image extraction, social-platform classification
├── search.py       SerpApi Google Lens client (URL search + real image-upload search), candidate parsing/ranking
├── manifest.py     canonical JSON serialization + deterministic SHA-256
├── ipfs.py         optional Pinata pinning (non-blocking on failure)
├── blockchain.py   web3.py: config, tx build/sign/send, receipt wait, read-only verify
├── models.py       every cross-module value is a typed dataclass — no bare dicts
├── reporting.py    Rich terminal rendering
├── cli.py          argument parsing, dispatch, the POL-protection confirmation gate
└── api.py          thin FastAPI adapter — zero duplicated logic, calls straight into pipeline.py
```

### The two flows

**`discover(image_path)`** — image-only, the primary Task 3 flow:
```
INPUT_VALIDATION -> FACE_ANALYSIS -> LIVE_SEARCH (image upload, real
SerpApi endpoint) -> CANDIDATE_PROCESSING (dedupe/normalize) ->
SOCIAL_SOURCE_VALIDATION (filter to real social platforms, fetch each
candidate in rank order, compare faces, skip failures rather than
trusting result #1) -> DISCOVERED or NO_MATCH
```
Never touches the blockchain. Candidates are tried in order until one
passes fetch + face-match — the code explicitly walks past unreachable
or non-matching candidates rather than assuming the top result is
correct (covered by a dedicated test).

**`register(image_path, claimed_url, dry_run)`** — claimed-source
verification, with optional on-chain anchoring:
```
INPUT_VALIDATION -> FACE_ANALYSIS -> SOURCE_FETCH -> FACE_COMPARISON ->
LIVE_SEARCH (original input image, same evidence standard as discover)
-> EVIDENCE_DECISION (VERIFIED or CORROBORATED) -> MANIFEST_BUILD ->
IPFS_PIN (optional) -> BLOCKCHAIN_REGISTER -> ON_CHAIN_VERIFY
```
`--dry-run` stops before `BLOCKCHAIN_REGISTER`. A real run requires
typed confirmation (`"confirm"` at the CLI, or the literal string
`"REGISTER"` at the API) — this exists specifically so a script bug or
an accidental key press can't spend testnet POL.

### Local API adapter

`src/api.py` exposes `discover`/`register`/`audit`/`check-config` over
HTTP for a future UI layer, with one deliberate asymmetry: `/api/verify`
and `/api/register` are **separate endpoints**, not one endpoint with a
dry-run flag — so a frontend bug can flip a boolean but can't
accidentally call the wrong route into a real transaction.

```bash
uvicorn src.api:app --reload --port 8000   # http://127.0.0.1:8000/docs
```

### Evidence states

```
REJECTED   NO_MATCH   DISCOVERED   VERIFIED   CORROBORATED
ON_CHAIN_VERIFIED   TAMPER_DETECTED
```
Every manifest also embeds a `verification_policy` block recording
*which rules* produced its status — a judge can see this without
reading source code.

---

## What it protects against — and what it doesn't

**Protects against**
- A claimed source that was never independently corroborated being
  reported as strongly verified — gated at `CORROBORATED`, never below.
- Post-hoc tampering with the local manifest: `audit` compares the
  current manifest hash against the hash that was *actually
  registered* (read from `verification.json`), not one re-derived from
  a possibly-tampered file — re-hashing a tampered manifest and looking
  that new hash up on-chain would just return "not found," not "found
  but mismatched." (This was a real bug we found and fixed while
  validating the audit path — see the checklist below.)
- False "verified" output from a failed/reverted transaction — nothing
  advances past `CORROBORATED` without a receipt `status == 1` **and**
  a separate read-only on-chain confirmation.
- Silent first-candidate selection — both `discover`'s social-source
  validation and `register`'s search-candidate matching explicitly
  iterate past failures rather than trusting the top result.
- Accidental blockchain writes — a confirmation gate (CLI prompt or
  API literal-string match) sits in front of every real transaction.

**Does not protect against**
- A source page itself being fraudulent or a deepfake — this checks
  *consistency*, not real-world ground truth.
- Search-index gaps — a genuine source SerpApi hasn't indexed yet
  correctly stops at `VERIFIED`/`NO_MATCH`, not a false negative bug.
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
  the manifest, the chain, or any API response — only a one-way
  `embedding_sha256` ever crosses a module boundary.
- The chain stores a 32-byte digest, submitter address, timestamp, and
  an optional IPFS URI. No images. No biometric vectors. No JSON.

---

## Setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

`dlib` has no prebuilt wheel on some platforms (notably Windows) and
builds from source — install `cmake` + a C++ toolchain first, or install
`dlib` via `conda-forge` to skip compiling entirely.

```bash
cp .env.example .env
# fill in: SERPAPI_API_KEY, POLYGON_AMOY_RPC_URL, CONTRACT_ADDRESS, PRIVATE_KEY
```

**SerpApi** — create an account, set `SERPAPI_API_KEY`. `discover` uses
the real image-upload endpoint (`POST /image` → `image_id`, 500 KB max,
JPG/PNG/WebP); `register` uses the URL-based `engine=google_lens` search.

**Polygon Amoy** — chain ID `80002`. Get an RPC URL (Alchemy/Infura/public
endpoint), fund a **testnet-only** wallet from the official Polygon
faucet, set `PRIVATE_KEY`. Never use a wallet holding real funds.

**Deploying the contract** — open [Remix](https://remix.ethereum.org),
paste `contracts/FaceVerificationRegistry.sol`, compile with Solidity
`^0.8.24`, deploy via Injected Provider on Amoy, copy the address into
`CONTRACT_ADDRESS`. The shipped ABI (`contracts/FaceVerificationRegistry.abi.json`)
is generated directly from source by the real `solc` compiler via
`scripts/compile_contract.py` — never hand-written.

---

## Commands

| Command | What it does | Touches the chain? |
|---|---|---|
| `discover --image <path>` | Image → matching social-media post, no URL needed | Never |
| `register --image <path> --url <url> --dry-run` | Full pipeline, stops before any transaction | Never |
| `register --image <path> --url <url>` | Full pipeline + real on-chain registration (prompts for typed confirmation, or pass `--yes`) | Yes |
| `check-config` | Confirms RPC/wallet/ABI/contract wiring | Read-only |
| `audit --manifest <path>` | Compares a manifest against what's actually registered on-chain; detects tampering | Read-only |

Natural demo flow: `discover` → feed its matched URL into
`register --dry-run` → confirm `CORROBORATED` → real `register` → `audit`.

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

Before any real registration exists, `audit` correctly reports
`NOT_REGISTERED` rather than a misleading chain lookup.

---

## Testing

```bash
pytest tests/ -v
```

78 tests, all passing. External services (SerpApi, Pinata, Polygon RPC)
are mocked in unit tests — no network calls or credentials required.
The live demo path itself is never mocked.

---

## Known limitations

- SerpApi's Image API caps uploads at 500 KB (JPG/PNG/WebP); `discover`
  fails closed rather than silently re-encoding oversized files, and
  the `image_id` it returns expires after 10 minutes.
- `discover` only searches an allowlist of real social platforms
  (x.com, instagram.com, facebook.com, linkedin.com, youtube.com,
  threads.net, tiktok.com) — a legitimate presence elsewhere correctly
  returns `NO_MATCH` rather than falling back to a non-social source.
- A genuine source SerpApi hasn't indexed yet correctly stops short of
  `CORROBORATED` — a provider limitation, not a bug.
- SerpApi/Pinata both have plan-based rate limits.
- Low light, extreme angles, heavy occlusion, or faces under ~60px fail
  quality checks by design; multi-face images are rejected rather than
  guessed at.
- RPC/IPFS outages surface as clear errors — IPFS failure is
  non-fatal (registration proceeds with an empty `manifestURI`); RPC
  failure is fatal by design.

---

## Project structure

```
hhgoa-provenance/
├── contracts/
│   ├── FaceVerificationRegistry.sol
│   ├── FaceVerificationRegistry.abi.json   (compiler-generated, see COMPILATION.md)
│   └── COMPILATION.md
├── scripts/
│   └── compile_contract.py     regenerates the ABI from source via real solc
├── src/
│   ├── pipeline.py     discover() + register() + audit() + check_config()
│   ├── vision.py        face detect, embed, compare
│   ├── source.py         claimed-URL fetch, canonicalize, extract image, social-platform classification
│   ├── search.py          SerpApi provider (URL search + real image upload), candidate ranking
│   ├── manifest.py        canonical JSON + SHA-256
│   ├── ipfs.py             Pinata pinning
│   ├── blockchain.py       web3.py tx build/send/verify
│   ├── models.py           typed dataclasses
│   ├── reporting.py        Rich terminal output
│   ├── cli.py              entrypoint + confirmation gate
│   └── api.py              FastAPI adapter for a UI layer
├── tests/               78 tests
├── examples/            demo image instructions (no images shipped)
├── proof/               generated manifest.json / verification.json
├── .env.example
├── requirements.txt
└── README.md
```

---

## Checklist

```
[x] image-only discovery (no URL required) -- the primary Task 3 flow
[x] genuine live reverse search (SerpApi, real upload endpoint, isolated provider module)
[x] social-media candidates distinguished from general web sources (real hostname allowlist)
[x] candidates validated in rank order, never results[0]
[x] supplied source verification (fetch + canonicalize + extract)
[x] source independently rediscovered from the ORIGINAL input image, not the source's own image
[x] face detection + embedding (face_recognition, pretrained, 128-d)
[x] face correspondence (distance vs. configurable threshold)
[x] no custom model training, no input->person dictionary
[x] deterministic canonical manifest (sorted-key JSON) + SHA-256
[x] verification policy versioned and embedded in every manifest
[x] raw embedding NOT on-chain, NOT in any API response (only embedding_sha256)
[x] IPFS support (Pinata, non-blocking failure)
[x] Polygon Amoy support (chain id 80002), compiler-verified ABI
[x] confirmation gate in front of every real transaction (CLI + API)
[x] receipt confirmation required (status==1) before advancing
[x] read-only on-chain verification (separate call from register)
[x] tamper detection compares against the ORIGINALLY REGISTERED hash (bug found + fixed)
[x] negative case (face mismatch / unreachable source -> REJECTED / NO_MATCH)
[x] local API adapter, zero duplicated business logic vs. CLI
[x] 78 tests passing
[ ] real on-chain registration -- deliberately deferred to the final demo
```
