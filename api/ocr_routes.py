"""Apple Vision OCR — the one impersonal capability in this service.

Reached by a *service* key (`ocr:read`, PRD decision #15), not a speaker-bound
one: there is no speaker involved, the caller is jarvis-ocr-service, and the
image is something it already holds.

Deliberately dumb: one image in, text out. Batching and tier fallback belong to
jarvis-ocr-service — this service owns stateless capability endpoints, not
orchestration.
"""

import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException

from api.deps import get_vision
from auth.dependencies import require_scope
from models.schemas import OCRRequest
from services.vision_ocr import BBOX_FORMAT, VisionUnavailableError

router = APIRouter(tags=["ocr"])


@router.post("/v1/ocr")
async def recognize_text(
    body: OCRRequest,
    _key=Depends(require_scope("ocr:read")),
    vision=Depends(get_vision),
):
    try:
        image_bytes = base64.b64decode(body.image_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"invalid_base64: {exc}") from exc
    if not image_bytes:
        raise HTTPException(status_code=400, detail="empty_image")

    try:
        result = vision.recognize(
            image_bytes,
            language_hints=body.language_hints,
            return_boxes=body.return_boxes,
        )
    except VisionUnavailableError as exc:
        # 503, not 502: the capability is absent on this host rather than having
        # failed. A caller can reasonably drop us from its tier list on this.
        raise HTTPException(status_code=503, detail="vision_unavailable") from exc
    except Exception as exc:
        # Never a 200 with empty text. jarvis-ocr-service reads an exception as
        # "try the next tier", but a successful-looking empty result reads as
        # "this page had no text" and gets accepted — which is exactly how four
        # separate silent-fallback bugs hid in this pipeline until 2026-08-23.
        raise HTTPException(status_code=502, detail=f"recognition_failed: {exc}") from exc

    return {**result, "bbox_format": BBOX_FORMAT}
