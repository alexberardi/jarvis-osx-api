"""Apple Vision text recognition.

Exposed so a Linux host can use it: jarvis-ocr-service runs a `remote_ocr`
provider pointed here. On a 5-image corpus of photographed cookbook pages this
returned 100% ingredient-line recall at ~1.6 s/image, against 75.4% for the best
provider that runs on Linux — which is the entire reason this endpoint exists.

Two bugs made the equivalent in-process provider in jarvis-ocr-service useless
for months. Both are avoided deliberately below; neither is obvious, and each
one alone is enough to break it completely:

1. `performRequests:error:` has an `NSError**` out-parameter, so PyObjC returns
   a **(success, error) tuple** — `(True, None)` on success. Assigning that to a
   variable named `error` and testing its truthiness raises on every *successful*
   recognition, because a 2-tuple is always truthy.
2. Vision's recognition levels are **Accurate = 0, Fast = 1**. They are easy to
   get backwards. Measured on one cookbook page: level 0 returned 94 text
   observations (~3000 chars); level 1 returned 1 observation (8 chars). For
   documents the fast path is not a speed/quality tradeoff, it is unusable.

Needs no TCC grant and no GUI session — unlike every other capability in this
service, this one is pure local image processing.
"""

import time

try:
    from CoreFoundation import NSData
    from Vision import VNImageRequestHandler, VNRecognizeTextRequest

    VISION_AVAILABLE = True
except ImportError:  # non-macOS, or pyobjc-framework-Vision not installed
    VISION_AVAILABLE = False

# VNRequestTextRecognitionLevel
RECOGNITION_LEVEL_ACCURATE = 0
RECOGNITION_LEVEL_FAST = 1

ENGINE = "apple_vision"

# Vision reports boxes normalized to [0,1] with a BOTTOM-left origin. We flip to
# a top-left origin (what every image toolkit and every other OCR provider in
# the stack uses) but keep them normalized, so the values survive any resizing
# the caller did before sending. Named explicitly on the wire so a consumer can
# never quietly misread them as pixels.
BBOX_FORMAT = "normalized_xywh_topleft"


class VisionUnavailableError(RuntimeError):
    """Raised when the Vision framework is not importable on this host."""


class VisionOCR:
    def recognize(
        self,
        image_bytes: bytes,
        language_hints: list[str] | None = None,
        return_boxes: bool = True,
    ) -> dict:
        if not VISION_AVAILABLE:
            raise VisionUnavailableError(
                "Vision framework unavailable — needs macOS and pyobjc-framework-Vision"
            )
        if not image_bytes:
            raise ValueError("image_bytes is empty")

        start = time.perf_counter()

        # Vision decodes JPEG/PNG/HEIC itself, so the bytes go straight in. No
        # Pillow round-trip: re-encoding would cost time and a dependency, and
        # is how the EXIF-orientation bug got introduced elsewhere.
        data = NSData.dataWithBytes_length_(image_bytes, len(image_bytes))
        handler = VNImageRequestHandler.alloc().initWithData_options_(data, {})

        request = VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(RECOGNITION_LEVEL_ACCURATE)
        request.setUsesLanguageCorrection_(True)
        if language_hints:
            request.setRecognitionLanguages_(language_hints)

        success, error = handler.performRequests_error_([request], None)
        if not success or error is not None:
            raise RuntimeError(f"Apple Vision recognition failed: {error}")

        parts: list[str] = []
        blocks: list[dict] = []
        for observation in request.results() or []:
            candidates = observation.topCandidates_(1)
            if not candidates:
                continue
            candidate = candidates[0]
            text = candidate.string()
            parts.append(text)
            if return_boxes:
                box = observation.boundingBox()
                blocks.append(
                    {
                        "text": text,
                        "bbox": [
                            box.origin.x,
                            1.0 - box.origin.y - box.size.height,  # bottom-left → top-left
                            box.size.width,
                            box.size.height,
                        ],
                        "confidence": float(candidate.confidence()),
                    }
                )

        return {
            # One observation per visual line, joined with newlines rather than
            # spaces: downstream this text is handed to an LLM to reconstruct a
            # structured document, and line breaks carry real layout signal that
            # a space-join destroys.
            "text": "\n".join(parts),
            "blocks": blocks,
            "duration_ms": (time.perf_counter() - start) * 1000,
            "engine": ENGINE,
        }
