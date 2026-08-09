from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from api.deps import get_chat_db, get_contacts, get_ledger
from auth.dependencies import require_scope
from models.schemas import MarkReadRequest, SendRequest
from services.chat_db import ChatDB, ChatDBUnreadable, ChatInfo, ChatMessage
from services.contacts import ContactsService
from services.ledger import ReadAloudLedger
from services.sender import MessageSender

router = APIRouter(tags=["messages"])

_SEND_STATUS_HTTP = {
    "no_such_chat": 404,
    "group_unsupported": 400,
    "applescript_error": 502,
    "send_failed": 502,
    "unverified": 502,
}


def _message_dict(m: ChatMessage, contacts: ContactsService) -> dict:
    sender_name = contacts.name_for_handle(m.sender_handle) if m.sender_handle else None
    return {
        "guid": m.guid,
        "sender_handle": m.sender_handle,
        "sender_name": sender_name,
        "is_from_me": m.is_from_me,
        "text": m.text,
        "spoken_text": m.spoken_text,
        "timestamp": m.timestamp,
        "timestamp_iso": datetime.fromtimestamp(m.timestamp, tz=timezone.utc).isoformat(),
        "has_attachments": m.has_attachments,
    }


def _chat_dict(m: ChatMessage) -> dict:
    return {
        "chat_id": m.chat_guid,
        "chat_rowid": m.chat_rowid,
        "identifier": m.chat_identifier,
        "display_name": m.chat_display_name,
        "is_group": m.is_group,
        "messages": [],
    }


def _resolve_chat(chat_db: ChatDB, chat_id: str) -> ChatInfo:
    info = (
        chat_db.chat_by_rowid(int(chat_id)) if chat_id.isdigit() else chat_db.chat_by_guid(chat_id)
    )
    if info is None:
        raise HTTPException(status_code=404, detail="no_such_chat")
    return info


@router.get("/v1/messages/unread")
async def unread_messages(
    _key=Depends(require_scope("messages:read")),
    chat_db: ChatDB = Depends(get_chat_db),
    ledger: ReadAloudLedger = Depends(get_ledger),
    contacts: ContactsService = Depends(get_contacts),
):
    try:
        messages = chat_db.unread()
    except ChatDBUnreadable:
        raise HTTPException(status_code=503, detail="chat_db_unreadable")
    # Ledger upkeep (decision #12): drop entries whose message was read on
    # another device, then hide what Jarvis already spoke.
    current_guids = {m.guid for m in messages}
    ledger.prune(still_unread=current_guids)
    already_spoken = ledger.marked()
    fresh = [m for m in messages if m.guid not in already_spoken]

    chats: dict[int, dict] = {}
    for m in fresh:
        chats.setdefault(m.chat_rowid, _chat_dict(m))["messages"].append(
            _message_dict(m, contacts)
        )
    return {"total": len(fresh), "chats": list(chats.values())}


@router.get("/v1/messages/threads/{chat_id}")
async def thread(
    chat_id: str,
    limit: int = 30,
    _key=Depends(require_scope("messages:read")),
    chat_db: ChatDB = Depends(get_chat_db),
    contacts: ContactsService = Depends(get_contacts),
):
    info = _resolve_chat(chat_db, chat_id)
    try:
        messages = chat_db.thread(info.rowid, limit=limit)
    except ChatDBUnreadable:
        raise HTTPException(status_code=503, detail="chat_db_unreadable")
    return {
        "chat_id": info.guid,
        "chat_rowid": info.rowid,
        "display_name": info.display_name,
        "is_group": info.is_group,
        "messages": [_message_dict(m, contacts) for m in messages],
    }


@router.get("/v1/messages/threads/{chat_id}/style-context")
async def style_context(
    chat_id: str,
    max_messages: int = 20,
    char_cap: int = 1500,
    _key=Depends(require_scope("messages:read")),
    chat_db: ChatDB = Depends(get_chat_db),
):
    info = _resolve_chat(chat_db, chat_id)
    try:
        return chat_db.style_context(info.rowid, max_messages=max_messages, char_cap=char_cap)
    except ChatDBUnreadable:
        raise HTTPException(status_code=503, detail="chat_db_unreadable")


@router.post("/v1/messages/mark-read")
async def mark_read(
    body: MarkReadRequest,
    _key=Depends(require_scope("messages:read")),
    ledger: ReadAloudLedger = Depends(get_ledger),
):
    return {"marked": ledger.mark(body.guids)}


@router.post("/v1/messages/send")
async def send_message(
    body: SendRequest,
    _key=Depends(require_scope("messages:send")),
    chat_db: ChatDB = Depends(get_chat_db),
):
    if not body.chat_id and not body.handle:
        raise HTTPException(status_code=422, detail="chat_id_or_handle_required")
    sender = MessageSender(chat_db)
    result = sender.send(body.text, chat_guid=body.chat_id, handle=body.handle)
    payload = {"status": result.status, "chat_id": result.chat_guid, "detail": result.detail}
    if result.ok:
        return payload
    return JSONResponse(status_code=_SEND_STATUS_HTTP.get(result.status, 500), content=payload)
