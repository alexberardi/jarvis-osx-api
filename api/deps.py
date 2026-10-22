"""Shared service dependencies.

ChatDB/Ledger are cheap and read their paths from settings at construction, so
they're built per-request (tests repoint via env vars). ContactsService is
cached because the pyobjc framework load and the handle→name cache are not.
"""

from services.chat_db import ChatDB
from services.contacts import ContactsService
from services.ledger import ReadAloudLedger
from services.vision_ocr import VisionOCR

_contacts: ContactsService | None = None
_vision: VisionOCR | None = None


def get_chat_db() -> ChatDB:
    return ChatDB()


def get_ledger() -> ReadAloudLedger:
    return ReadAloudLedger()


def get_contacts() -> ContactsService:
    global _contacts
    if _contacts is None:
        _contacts = ContactsService()
    return _contacts


def get_vision() -> VisionOCR:
    """Cached: the Vision framework load is the expensive part, the recognizer
    itself is stateless."""
    global _vision
    if _vision is None:
        _vision = VisionOCR()
    return _vision
