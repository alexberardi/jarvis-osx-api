"""Health with per-capability TCC probes (PRD decision #8).

TCC failures are the dominant failure mode and they're silent — surface them
here. 200-with-status-body for degraded-but-alive; non-2xx only when down
(the process being up to answer means "up").
"""

from fastapi import APIRouter, Depends

from api.deps import get_chat_db, get_contacts
from services.chat_db import ChatDB
from services.contacts import ContactsService
from services.shortcuts import shortcuts_cli_present
from version import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    chat_db: ChatDB = Depends(get_chat_db),
    contacts: ContactsService = Depends(get_contacts),
):
    messages_db = "readable" if chat_db.probe() else "unreadable"
    capabilities = {
        "messages_db": messages_db,
        "contacts": contacts.authorization_status(),
        "shortcuts_cli": "present" if shortcuts_cli_present() else "missing",
        # Not probeable without triggering a real send — setup docs include a
        # one-time test-send-to-self.
        "automation": "unknown",
    }
    degraded = messages_db != "readable" or capabilities["contacts"] not in (
        "authorized",
        "limited",
    )
    return {
        "status": "degraded" if degraded else "ok",
        "version": __version__,
        "capabilities": capabilities,
    }


@router.get("/ping")
async def ping():
    return {"message": "pong"}
