"""Apple Vision OCR capability + the speaker/service key split (decision #15).

Two things under test and they are deliberately in one file, because the whole
point of the OCR capability is that it is the first *impersonal* one: it is
reached by a service, not by a speaker, and the key that reaches it must not be
able to touch anyone's messages.

Vision itself is stubbed here. A real-device check lives at the bottom, skipped
off macOS.
"""

import base64
from pathlib import Path

import pytest

from auth.api_keys import SERVICE_SCOPES, SPEAKER_SCOPES, VALID_SCOPES, ApiKeyStore, InvalidScopeError


@pytest.fixture()
def store(tmp_path):
    return ApiKeyStore(tmp_path / "api_keys.json")


class FakeVision:
    """Stands in for VisionOCR — the real thing needs macOS + pyobjc."""

    def __init__(self, text="Spicy Beef Rice Bowls", blocks=None, raises=None):
        self._text = text
        self._blocks = blocks if blocks is not None else [
            {"text": "Spicy Beef Rice Bowls", "bbox": [0.1, 0.8, 0.5, 0.05], "confidence": 0.99}
        ]
        self._raises = raises
        self.calls = []

    def recognize(self, image_bytes, language_hints=None, return_boxes=True):
        if self._raises:
            raise self._raises
        self.calls.append(
            {"bytes": len(image_bytes), "language_hints": language_hints, "return_boxes": return_boxes}
        )
        return {
            "text": self._text,
            "blocks": self._blocks if return_boxes else [],
            "duration_ms": 1640.0,
            "engine": "apple_vision",
        }


@pytest.fixture()
def fake_vision():
    return FakeVision()


@pytest.fixture()
def ocr_client(fx, fake_contacts, fake_vision):
    from fastapi.testclient import TestClient

    from api.deps import get_contacts, get_vision
    from main import app

    app.dependency_overrides[get_contacts] = lambda: fake_contacts
    app.dependency_overrides[get_vision] = lambda: fake_vision
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _png_b64() -> str:
    """A 1x1 PNG. Vision is stubbed, so only the base64 round-trip matters."""
    raw = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    return base64.b64encode(raw).decode()


class TestKeyClasses:
    """Decision #15: two classes of key over one store."""

    def test_ocr_read_is_a_valid_service_scope(self):
        assert "ocr:read" in VALID_SCOPES
        assert "ocr:read" in SERVICE_SCOPES
        assert "ocr:read" not in SPEAKER_SCOPES

    def test_scope_classes_do_not_overlap(self):
        assert SPEAKER_SCOPES & SERVICE_SCOPES == frozenset()
        assert SPEAKER_SCOPES | SERVICE_SCOPES == VALID_SCOPES

    def test_mixed_class_key_is_refused(self, store):
        """The containment guarantee: no single key may reach both a person's
        messages and an impersonal capability. If this can be minted, a
        compromised ocr-service key could read iMessage."""
        with pytest.raises(InvalidScopeError):
            store.generate(["ocr:read", "messages:read"])

    def test_key_class_is_derived_from_scopes(self, store):
        _, service_key = store.generate(["ocr:read"])
        _, speaker_key = store.generate(["messages:read", "contacts:read"])
        assert service_key.key_class == "service"
        assert speaker_key.key_class == "speaker"

    def test_single_class_keys_still_mint(self, store):
        raw, key = store.generate(["ocr:read"], name="jarvis-ocr-service")
        assert store.verify(raw).scopes == ["ocr:read"]
        assert key.name == "jarvis-ocr-service"


class TestOCRAuth:
    def test_missing_token_401(self, ocr_client):
        r = ocr_client.post("/v1/ocr", json={"image_base64": _png_b64()})
        assert r.status_code == 401

    def test_speaker_key_cannot_reach_ocr(self, ocr_client, key_factory):
        """A speaker-bound key is not an OCR key, even though both are joxk_."""
        r = ocr_client.post(
            "/v1/ocr", json={"image_base64": _png_b64()}, headers=key_factory("messages:read")
        )
        assert r.status_code == 403

    def test_service_key_cannot_reach_messages(self, ocr_client, key_factory):
        """The inverse, and the one that actually bounds the blast radius."""
        r = ocr_client.get("/v1/messages/unread", headers=key_factory("ocr:read"))
        assert r.status_code == 403

    def test_service_key_reaches_ocr(self, ocr_client, key_factory):
        r = ocr_client.post(
            "/v1/ocr", json={"image_base64": _png_b64()}, headers=key_factory("ocr:read")
        )
        assert r.status_code == 200


class TestOCRContract:
    def test_returns_text_blocks_and_timing(self, ocr_client, key_factory):
        r = ocr_client.post(
            "/v1/ocr", json={"image_base64": _png_b64()}, headers=key_factory("ocr:read")
        )
        body = r.json()
        assert body["text"] == "Spicy Beef Rice Bowls"
        assert body["engine"] == "apple_vision"
        assert body["duration_ms"] > 0
        block = body["blocks"][0]
        assert set(block) == {"text", "bbox", "confidence"}
        assert len(block["bbox"]) == 4

    def test_return_boxes_false_drops_blocks_but_keeps_text(self, ocr_client, key_factory):
        r = ocr_client.post(
            "/v1/ocr",
            json={"image_base64": _png_b64(), "return_boxes": False},
            headers=key_factory("ocr:read"),
        )
        body = r.json()
        assert body["blocks"] == []
        assert body["text"]

    def test_language_hints_reach_the_recognizer(self, ocr_client, key_factory, fake_vision):
        ocr_client.post(
            "/v1/ocr",
            json={"image_base64": _png_b64(), "language_hints": ["en", "fr"]},
            headers=key_factory("ocr:read"),
        )
        assert fake_vision.calls[0]["language_hints"] == ["en", "fr"]

    def test_undecodable_base64_is_400_not_500(self, ocr_client, key_factory):
        r = ocr_client.post(
            "/v1/ocr", json={"image_base64": "!!!not base64!!!"}, headers=key_factory("ocr:read")
        )
        assert r.status_code == 400

    def test_missing_image_is_422(self, ocr_client, key_factory):
        r = ocr_client.post("/v1/ocr", json={}, headers=key_factory("ocr:read"))
        assert r.status_code == 422

    def test_recognizer_failure_surfaces_as_502_not_a_silent_empty_result(
        self, ocr_client, key_factory, fx, fake_contacts
    ):
        """Never return 200-with-empty-text on a recognizer error.

        jarvis-ocr-service treats a provider exception as 'try the next tier'.
        If a Vision failure came back as an empty 200 it would look like a
        successful OCR of a blank page, and the caller would accept it instead
        of falling through. Four separate silent-fallback bugs were found in
        this pipeline on 2026-08-23; this is the guard against a fifth.
        """
        from fastapi.testclient import TestClient

        from api.deps import get_contacts, get_vision
        from main import app

        app.dependency_overrides[get_contacts] = lambda: fake_contacts
        app.dependency_overrides[get_vision] = lambda: FakeVision(raises=RuntimeError("Vision exploded"))
        try:
            with TestClient(app) as c:
                raw, _ = ApiKeyStore().generate(["ocr:read"], name="t")
                r = c.post(
                    "/v1/ocr",
                    json={"image_base64": _png_b64()},
                    headers={"Authorization": f"Bearer {raw}"},
                )
            assert r.status_code == 502
        finally:
            app.dependency_overrides.clear()


def _vision_available() -> bool:
    try:
        import Vision  # noqa: F401

        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _vision_available(), reason="Vision framework not available (non-macOS)")
class TestRealVision:
    """The only tests here that touch the actual framework.

    They guard the two bugs that made the equivalent in-process provider in
    jarvis-ocr-service useless for months, and neither is catchable with a stub:

    1. PyObjC returns (success, error) from `performRequests:error:`. Reading
       that 2-tuple as an error raises on every *successful* recognition.
    2. Recognition level 1 is Fast, not Accurate. On a document the fast path
       returned 1 observation of 8 characters where Accurate returned 94
       observations totalling ~3000 — so "it returned something" is not enough;
       the assertion has to be that it read the actual words.
    """

    def _sample(self) -> bytes:
        return (Path(__file__).parent / "data" / "ocr_sample.png").read_bytes()

    def test_reads_the_words_in_the_image(self):
        from services.vision_ocr import VisionOCR

        result = VisionOCR().recognize(self._sample(), language_hints=["en"])
        assert "JARVIS" in result["text"].upper()
        assert result["engine"] == "apple_vision"
        assert result["duration_ms"] > 0

    def test_blocks_carry_confidence_and_a_normalized_top_left_bbox(self):
        from services.vision_ocr import VisionOCR

        block = VisionOCR().recognize(self._sample())["blocks"][0]
        assert 0.0 < block["confidence"] <= 1.0
        x, y, w, h = block["bbox"]
        assert all(0.0 <= v <= 1.0 for v in (x, y, w, h)), "bbox must be normalized"
        # The text sits in the upper-middle of the image. With Vision's native
        # bottom-left origin this y would be ~0.35 from the BOTTOM; the flip to
        # top-left is what makes this assertion meaningful.
        assert y < 0.5

    def test_return_boxes_false_still_reads_text(self):
        from services.vision_ocr import VisionOCR

        result = VisionOCR().recognize(self._sample(), return_boxes=False)
        assert result["blocks"] == []
        assert "JARVIS" in result["text"].upper()

    def test_too_small_image_raises_rather_than_returning_empty(self):
        """Vision rejects images <= 2px per side. It must surface as an error,
        not as a successful OCR of a blank page."""
        from services.vision_ocr import VisionOCR

        with pytest.raises(RuntimeError, match="Apple Vision recognition failed"):
            VisionOCR().recognize(base64.b64decode(_png_b64()))
