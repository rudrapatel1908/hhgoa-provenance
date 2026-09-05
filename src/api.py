"""
Thin API adapter. Contains NO business logic of its own -- every
endpoint calls straight into the same pipeline.py functions the CLI
uses (discover, register, audit, check_config). This is deliberate:
the CLI and any future UI must produce the same truth, from the same
code path, always.

Run locally with:
    uvicorn src.api:app --reload --port 8000

Never deployed publicly -- localhost only, per project scope.
"""

from __future__ import annotations

import asyncio
import dataclasses
import enum
import json
import queue
import shutil
import tempfile
import threading
from pathlib import Path
from typing import AsyncIterator, Callable, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from . import pipeline

load_dotenv()

app = FastAPI(title="HH Goa Provenance API", version="1.0")

# Localhost-only frontend dev servers. Never widen this for a public
# deployment -- this project is explicitly localhost-only.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# The ONLY string that authorizes a real (non-dry-run) blockchain write
# through this API. A frontend bug that sends the wrong boolean, or an
# empty/missing field, can never accidentally trigger a real transaction
# -- it must match this literal value exactly.
REGISTER_CONFIRMATION_STRING = "REGISTER"


def _to_jsonable(obj):
    """Recursively convert dataclasses/enums/bytes into JSON-safe values.
    Never serializes raw embedding vectors -- those never appear in any
    dataclass returned to the API layer in the first place (see
    models.py: only *_sha256 fields leave vision.py)."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {k: _to_jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, enum.Enum):
        return obj.value
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, bytes):
        return obj.hex()
    return obj


def _save_upload_to_temp(image: UploadFile) -> str:
    suffix = Path(image.filename or "upload.jpg").suffix or ".jpg"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    with tmp as f:
        shutil.copyfileobj(image.file, f)
    return tmp.name


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def _stream_pipeline_run(run: Callable[[Callable], object]) -> AsyncIterator[str]:
    """
    Runs a blocking pipeline call (discover/register) in a background
    thread, forwarding each StageRecord to the client the instant it's
    actually emitted by pipeline.py -- never buffered until the run
    finishes, never a simulated/fixed-duration animation. `run` must be
    a zero-extra-arg closure that accepts a single on_stage callback and
    returns the final PipelineResult/DiscoveryResult (or raises).

    The final SSE event always carries the complete, real result object
    -- same dataclass the CLI prints from -- so the frontend's terminal
    state is never inferred from partial stage events.
    """
    loop = asyncio.get_event_loop()
    q: "queue.Queue" = queue.Queue()
    DONE = object()
    outcome: dict = {}

    def on_stage(record) -> None:
        q.put(("stage", _to_jsonable(record)))

    def worker() -> None:
        try:
            outcome["result"] = run(on_stage)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the client, never swallowed
            outcome["error"] = str(exc)
        finally:
            q.put((DONE, None))

    threading.Thread(target=worker, daemon=True).start()

    while True:
        kind, payload = await loop.run_in_executor(None, q.get)
        if kind is DONE:
            break
        yield _sse(kind, payload)

    if "error" in outcome:
        yield _sse("error", {"detail": outcome["error"]})
    else:
        yield _sse("result", _to_jsonable(outcome["result"]))


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/check-config")
def check_config_endpoint():
    result = pipeline.check_config()
    status_code = 200 if result["ok"] else 503
    return JSONResponse(content=result, status_code=status_code)


@app.post("/api/discover")
async def discover_endpoint(image: UploadFile = File(...)):
    image_path = _save_upload_to_temp(image)
    try:
        result = pipeline.discover(image_path=image_path)
    finally:
        Path(image_path).unlink(missing_ok=True)
    return _to_jsonable(result)


@app.post("/api/verify")
async def verify_endpoint(image: UploadFile = File(...), url: str = Form(...)):
    """Off-chain verification only. This endpoint is ALWAYS dry-run --
    there is no parameter that can change that. A separate endpoint
    (/api/register) exists for the one deliberate real write, so a
    frontend bug here can never cause a blockchain transaction."""
    image_path = _save_upload_to_temp(image)
    try:
        result = pipeline.register(image_path=image_path, claimed_url=url, dry_run=True)
    finally:
        Path(image_path).unlink(missing_ok=True)
    return _to_jsonable(result)


@app.post("/api/register")
async def register_endpoint(
    image: UploadFile = File(...),
    url: str = Form(...),
    confirm: str = Form(...),
):
    """The one endpoint capable of a real blockchain write. Requires the
    literal confirmation string as a second, independent gate beyond
    whatever the frontend's own 'explicit click' UX provides."""
    if confirm != REGISTER_CONFIRMATION_STRING:
        raise HTTPException(
            status_code=400,
            detail=f"confirmation_required: 'confirm' must equal '{REGISTER_CONFIRMATION_STRING}'",
        )
    image_path = _save_upload_to_temp(image)
    try:
        result = pipeline.register(image_path=image_path, claimed_url=url, dry_run=False)
    finally:
        Path(image_path).unlink(missing_ok=True)
    return _to_jsonable(result)


@app.post("/api/discover/stream")
async def discover_stream_endpoint(image: UploadFile = File(...)):
    """Same call as /api/discover, but emits each real StageRecord over
    Server-Sent Events as the pipeline actually produces it. Never sends
    a blockchain transaction -- discover() cannot reach that code path."""
    image_path = _save_upload_to_temp(image)

    def run(on_stage):
        try:
            return pipeline.discover(image_path=image_path, on_stage=on_stage)
        finally:
            Path(image_path).unlink(missing_ok=True)

    return StreamingResponse(_stream_pipeline_run(run), media_type="text/event-stream")


@app.post("/api/verify/stream")
async def verify_stream_endpoint(image: UploadFile = File(...), url: str = Form(...)):
    """Streaming counterpart to /api/verify. Hardcoded dry_run=True, same
    as the non-streaming endpoint -- no parameter can change that."""
    image_path = _save_upload_to_temp(image)

    def run(on_stage):
        try:
            return pipeline.register(
                image_path=image_path, claimed_url=url, dry_run=True, on_stage=on_stage,
            )
        finally:
            Path(image_path).unlink(missing_ok=True)

    return StreamingResponse(_stream_pipeline_run(run), media_type="text/event-stream")


@app.post("/api/register/stream")
async def register_stream_endpoint(
    image: UploadFile = File(...),
    url: str = Form(...),
    confirm: str = Form(...),
):
    """Streaming counterpart to /api/register -- the one endpoint capable
    of a real blockchain write. Same literal-confirmation gate as the
    non-streaming endpoint, checked before any pipeline work starts."""
    if confirm != REGISTER_CONFIRMATION_STRING:
        raise HTTPException(
            status_code=400,
            detail=f"confirmation_required: 'confirm' must equal '{REGISTER_CONFIRMATION_STRING}'",
        )
    image_path = _save_upload_to_temp(image)

    def run(on_stage):
        try:
            return pipeline.register(
                image_path=image_path, claimed_url=url, dry_run=False, on_stage=on_stage,
            )
        finally:
            Path(image_path).unlink(missing_ok=True)

    return StreamingResponse(_stream_pipeline_run(run), media_type="text/event-stream")


@app.get("/api/audit")
def audit_endpoint(manifest: str, verification: Optional[str] = None):
    manifest_path = Path(manifest)
    if not manifest_path.is_file():
        raise HTTPException(status_code=404, detail=f"manifest not found: {manifest}")
    result = pipeline.audit(str(manifest_path), verification_path=verification)
    return result
