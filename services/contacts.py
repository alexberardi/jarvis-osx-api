"""Contacts resolution via the Contacts framework (pyobjc).

Requires the Contacts TCC grant. Degrades gracefully: pyobjc missing →
"unavailable"; not authorized → empty results. The framework object is
injectable for tests (real behavior needs a granted device — see
tests/manual/).
"""

import logging

logger = logging.getLogger("uvicorn")

_STATUS_MAP = {
    0: "notDetermined",
    1: "restricted",
    2: "denied",
    3: "authorized",
    4: "limited",
}


def _load_framework():
    try:
        import Contacts  # pyobjc-framework-Contacts

        return Contacts
    except ImportError:
        return None


def _normalize(handle: str) -> str:
    handle = handle.strip().lower()
    if "@" in handle or any(c.isalpha() for c in handle):
        return handle
    digits = "".join(ch for ch in handle if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else digits


class ContactsService:
    _UNSET = object()

    def __init__(self, framework=_UNSET):
        self._fw = _load_framework() if framework is self._UNSET else framework
        self._handle_to_name: dict[str, str] | None = None

    def authorization_status(self) -> str:
        if self._fw is None:
            return "unavailable"
        status = self._fw.CNContactStore.authorizationStatusForEntityType_(
            self._fw.CNEntityTypeContacts
        )
        return _STATUS_MAP.get(status, "unknown")

    def resolve(self, query: str) -> list[dict]:
        """Name → handles. Empty list when unauthorized/unavailable."""
        if self.authorization_status() != "authorized":
            return []
        fw = self._fw
        store = fw.CNContactStore.alloc().init()
        predicate = fw.CNContact.predicateForContactsMatchingName_(query)
        keys = [
            fw.CNContactGivenNameKey,
            fw.CNContactFamilyNameKey,
            fw.CNContactNicknameKey,
            fw.CNContactPhoneNumbersKey,
            fw.CNContactEmailAddressesKey,
        ]
        contacts, error = store.unifiedContactsMatchingPredicate_keysToFetch_error_(
            predicate, keys, None
        )
        if error is not None or contacts is None:
            logger.warning("contacts resolve failed: %s", error)
            return []
        results = []
        for contact in contacts:
            handles = []
            for labeled in contact.phoneNumbers() or []:
                handles.append({"value": labeled.value().stringValue(), "kind": "phone"})
            for labeled in contact.emailAddresses() or []:
                handles.append({"value": str(labeled.value()), "kind": "email"})
            name = " ".join(
                part for part in (contact.givenName(), contact.familyName()) if part
            ).strip()
            nickname = contact.nickname() or ""
            results.append({"name": name or nickname, "nickname": nickname, "handles": handles})
        return results

    def name_for_handle(self, handle: str) -> str | None:
        """Reverse lookup for message listings. None when unauthorized/unknown."""
        cache = self._handle_cache()
        if cache is None:
            return None
        return cache.get(_normalize(handle))

    def _handle_cache(self) -> dict[str, str] | None:
        if self._handle_to_name is not None:
            return self._handle_to_name
        if self.authorization_status() != "authorized":
            return None
        fw = self._fw
        store = fw.CNContactStore.alloc().init()
        keys = [
            fw.CNContactGivenNameKey,
            fw.CNContactFamilyNameKey,
            fw.CNContactPhoneNumbersKey,
            fw.CNContactEmailAddressesKey,
        ]
        request = fw.CNContactFetchRequest.alloc().initWithKeysToFetch_(keys)
        cache: dict[str, str] = {}

        def _visit(contact, _stop):
            name = " ".join(
                part for part in (contact.givenName(), contact.familyName()) if part
            ).strip()
            if not name:
                return
            for labeled in contact.phoneNumbers() or []:
                cache[_normalize(labeled.value().stringValue())] = name
            for labeled in contact.emailAddresses() or []:
                cache[_normalize(str(labeled.value()))] = name

        ok, error = store.enumerateContactsWithFetchRequest_error_usingBlock_(
            request, None, _visit
        )
        if not ok:
            logger.warning("contacts enumeration failed: %s", error)
            return None
        self._handle_to_name = cache
        return cache

    def invalidate_cache(self) -> None:
        self._handle_to_name = None
