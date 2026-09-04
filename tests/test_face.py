"""
Tests vision.py's face-count policy and comparison logic without
requiring dlib/face_recognition to be installed, by mocking the lazily
imported `_fr()` accessor. This keeps the test suite runnable in CI
environments where the (heavy, native) dlib dependency isn't set up.
"""

import io
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

from src import vision


def _tiny_image_bytes():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), color="blue").save(buf, format="JPEG")
    return buf.getvalue()


def test_zero_faces_rejected():
    fake_fr = MagicMock()
    fake_fr.face_locations.return_value = []
    with patch.object(vision, "_fr", return_value=fake_fr):
        result = vision.analyze_face(_tiny_image_bytes())
    assert result.face_count == 0
    assert not result.usable
    assert result.error == "no_face_detected"


def test_multi_face_rejected_by_default():
    fake_fr = MagicMock()
    fake_fr.face_locations.return_value = [(0, 80, 80, 0), (10, 90, 90, 10)]
    with patch.object(vision, "_fr", return_value=fake_fr):
        result = vision.analyze_face(_tiny_image_bytes())
    assert result.face_count == 2
    assert not result.usable
    assert result.error == "multiple_faces_ambiguous"


def test_single_face_usable():
    fake_fr = MagicMock()
    fake_fr.face_locations.return_value = [(0, 90, 90, 0)]  # 90px wide box
    fake_fr.face_encodings.return_value = [np.array([0.1] * 128)]
    with patch.object(vision, "_fr", return_value=fake_fr):
        result = vision.analyze_face(_tiny_image_bytes())
    assert result.face_count == 1
    assert result.usable
    assert result.embedding_sha256 is not None


def test_face_too_small_rejected():
    fake_fr = MagicMock()
    fake_fr.face_locations.return_value = [(0, 20, 20, 0)]  # 20px, below MIN_FACE_WIDTH_PX
    with patch.object(vision, "_fr", return_value=fake_fr):
        result = vision.analyze_face(_tiny_image_bytes())
    assert not result.usable
    assert result.error == "quality_check_failed"


def test_malformed_image_fails_closed():
    result = vision.analyze_face(b"not an image")
    assert result.face_count == 0
    assert result.error == "image_decode_failed"


def test_compare_faces_uses_configured_threshold():
    fake_fr = MagicMock()
    fake_fr.face_distance.return_value = np.array([0.5])
    with patch.object(vision, "_fr", return_value=fake_fr):
        result_pass = vision.compare_faces([0.1] * 128, [0.1] * 128, threshold=0.6)
        result_fail = vision.compare_faces([0.1] * 128, [0.1] * 128, threshold=0.4)

    assert result_pass.distance == 0.5
    assert result_pass.decision.value == "pass"
    assert result_fail.decision.value == "fail"


def test_embedding_never_included_in_hash_only_output():
    """Guards against accidentally exposing the raw embedding where only
    its hash should appear -- embedding_sha256 must be a 64-char hex
    string, distinct from the raw vector."""
    fake_fr = MagicMock()
    fake_fr.face_locations.return_value = [(0, 90, 90, 0)]
    fake_fr.face_encodings.return_value = [np.array([0.2] * 128)]
    with patch.object(vision, "_fr", return_value=fake_fr):
        result = vision.analyze_face(_tiny_image_bytes())
    assert len(result.embedding_sha256) == 64
    int(result.embedding_sha256, 16)  # raises if not valid hex
