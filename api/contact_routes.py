from fastapi import APIRouter, Depends, Query

from api.deps import get_contacts
from auth.dependencies import require_scope
from services.contacts import ContactsService

router = APIRouter(tags=["contacts"])


@router.get("/v1/contacts/resolve")
async def resolve_contact(
    query: str = Query(min_length=1),
    _key=Depends(require_scope("contacts:read")),
    contacts: ContactsService = Depends(get_contacts),
):
    """Name → handles (for "text Mom"). `authorization` tells callers apart
    "no match" from "no Contacts permission"."""
    return {
        "authorization": contacts.authorization_status(),
        "results": contacts.resolve(query),
    }
