"""
Face analysis: detection, quality checks, embedding extraction, and
comparison. Uses pretrained inference only (face_recognition / dlib).
No training, no custom classifiers, no input->person dictionaries.
"""

from __future__ import annotations

import hashlib
import io
import logging
from typing import Optional

import numpy as np
from PIL import Image

from .models import FaceComparisonResult, FaceEvidence, StageStatus

logger = logging.getLogger(__name__)

# face_recognition wraps dlib. Imported lazily so that modules which don't
# need vision (e.g. manifest tests) don't require dlib to be installed.
_face_recognition = None


def _fr():
    global _face_recognition
    if _face_recognition is None:
        import face_recognition  # noqa: local import by design
        _face_recognition = face_recognition
    return _face_recognition


MIN_FACE_WIDTH_PX = 60  # below this, embeddings are unreliable


def decode_image(image_bytes: bytes) -> Optional[np.ndarray]:
    """Decode arbitrary image bytes to an RGB numpy array. Returns None
    (never raises) on malformed input -- callers must fail closed."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            img = img.convert("RGB")
            return np.array(img)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, logged
        logger.warning("decode_image failed: %s", exc)
        return None


def analyze_face(image_bytes: bytes, *, allow_multi_face: bool = False) -> FaceEvidence:
    """
    Run the face pipeline on one image:
      decode -> detect -> count check -> quality check -> embed -> hash

    Default policy (non-negotiable unless allow_multi_face=True):
        0 faces  -> FaceEvidence with face_count=0, not usable
        1 face   -> proceed
        >1 faces -> rejected as ambiguous, NOT silently first-face-picked
    """
    rgb = decode_image(image_bytes)
    if rgb is None:
        return FaceEvidence(face_count=0, error="image_decode_failed")

    fr = _fr()
    locations = fr.face_locations(rgb, model="hog")
    face_count = len(locations)

    if face_count == 0:
        return FaceEvidence(face_count=0, error="no_face_detected")

    if face_count > 1 and not allow_multi_face:
        return FaceEvidence(
            face_count=face_count,
            error="multiple_faces_ambiguous",
            quality_notes=[f"{face_count} faces detected; default policy rejects ambiguous images"],
        )

    # Quality: reject faces too small to embed reliably.
    top, right, bottom, left = locations[0]
    face_width = right - left
    face_height = bottom - top
    quality_notes = []
    quality_pass = True
    if face_width < MIN_FACE_WIDTH_PX or face_height < MIN_FACE_WIDTH_PX:
        quality_pass = False
        quality_notes.append(
            f"face bounding box too small ({face_width}x{face_height}px, "
            f"minimum {MIN_FACE_WIDTH_PX}px)"
        )

    if not quality_pass:
        return FaceEvidence(
            face_count=face_count,
            quality_pass=False,
            quality_notes=quality_notes,
            error="quality_check_failed",
        )

    encodings = fr.face_encodings(rgb, known_face_locations=[locations[0]])
    if not encodings:
        return FaceEvidence(face_count=face_count, error="embedding_extraction_failed")

    embedding = encodings[0]
    embedding_bytes = np.asarray(embedding, dtype=np.float64).tobytes()
    embedding_sha256 = hashlib.sha256(embedding_bytes).hexdigest()

    return FaceEvidence(
        face_count=face_count,
        embedding=embedding.tolist(),
        embedding_sha256=embedding_sha256,
        quality_pass=True,
        quality_notes=quality_notes,
    )


def compare_faces(
    embedding_a: list,
    embedding_b: list,
    *,
    threshold: float,
) -> FaceComparisonResult:
    """
    Compare two face embeddings using face_recognition's standard
    Euclidean distance metric. Never reports a fabricated percentage --
    only distance, threshold, and a pass/fail decision.
    """
    fr = _fr()
    distance = float(
        fr.face_distance([np.asarray(embedding_a)], np.asarray(embedding_b))[0]
    )
    decision = StageStatus.PASS if distance <= threshold else StageStatus.FAIL
    return FaceComparisonResult(
        method="face_recognition.face_distance",
        distance=distance,
        threshold=threshold,
        decision=decision,
    )
