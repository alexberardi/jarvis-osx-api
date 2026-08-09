# jarvis-osx-api

macOS personal-data bridge: exposes Mac-resident personal data (iMessage,
Contacts, Shortcuts) to Jarvis over a FastAPI REST surface on **port 7723**.
Design doc: `jarvis/prds/osx-api.md` (meta repo) — read it before changing
behavior; the locked decisions there are binding.

> **This is the most sensitive service in the stack**: every text ever
> sent/received, plus the ability to impersonate the user in writing.

---

## Hard rules

1. **Native-only, never Docker.** Needs host TCC grants (Full Disk Access,
   Automation, Contacts) and a **logged-in GUI session** (LaunchAgent, not
   LaunchDaemon) or AppleScript sends fail. The admin registry marks it
   `nativeOnly` — it must never appear in any compose file on any platform.
2. **Never write to chat.db.** It's a live WAL database owned by Messages.app.
   All connections are `mode=ro` (`services/chat_db.py`). The read-aloud state
   lives in our own ledger DB instead.
3. **Sends are never trusted on AppleScript's word.** `services/sender.py`
   polls chat.db after the send and only reports `sent` when the row actually
   landed (`is_from_me=1`, matching text, `error=0`). The Tahoe ghost-message
   bug is why. Do not remove the verification step.
4. **1:1 existing chats only in v1.** Group sends via AppleScript are broken on
   macOS 26 (GUID mismatch → error or ghost "success"). New-thread creation +
   iMessage-vs-SMS service selection is unverified on-device. Both are
   explicitly refused, not attempted.
5. **Auth is self-contained.** Locally-minted scoped bearer keys
   (`auth/api_keys.py`, `python cli.py generate-api-key`), SHA-256-hashed at
   rest, raw shown once. No jarvis-auth round-trip on any request path. Scopes:
   `messages:read`, `messages:send`, `contacts:read`, `shortcuts:run` —
   read ≠ send is the point; keep them separate.
6. **Message bodies stay out of logs.** JarvisLogger events carry metadata only
   (chat ids, counts, durations). Never log message text.

---

## Quick reference

```bash
./run.sh                                 # dev (venv auto-setup, reload)
.venv/bin/python -m pytest -q            # tests (no Mac permissions needed)
./deploy-launchd.sh                      # install as LaunchAgent (com.jarvis.osx-api)
python cli.py generate-api-key --scopes messages:read,contacts:read --name kitchen-node
curl localhost:7723/health               # per-capability TCC probe report
```

Logs (launchd mode): `~/Library/Logs/jarvis-osx-api/{out,err}.log`.

---

## API surface

| Method | Path | Scope |
|---|---|---|
| GET | `/health` (+ `/ping`) | none |
| GET | `/v1/messages/unread` | `messages:read` |
| GET | `/v1/messages/threads/{chat_id}` | `messages:read` |
| GET | `/v1/messages/threads/{chat_id}/style-context` | `messages:read` |
| POST | `/v1/messages/mark-read` | `messages:read` |
| POST | `/v1/messages/send` | `messages:send` |
| GET | `/v1/contacts/resolve?query=` | `contacts:read` |
| POST | `/v1/shortcuts/run` | `shortcuts:run` |

`{chat_id}` accepts a chat GUID or a numeric chat ROWID. Send accepts
`chat_id` or `handle` (handle must resolve to an existing 1:1 chat).

**Unread semantics (PRD decisions #2 + #12):** unread = chat.db `is_read = 0`
(syncs across devices) AND not in the local **read-aloud ledger**
(`~/.jarvis/osx-api/read_aloud_ledger.db`). The caller POSTs `mark-read` with
GUIDs *after actually speaking them*; the ledger auto-prunes entries once the
message is read on another device. This ledger is the one deliberate exception
to the service's statelessness.

---

## Architecture

```
main.py                 # FastAPI wiring + optional jarvis config/log client init
cli.py                  # generate/list/revoke API keys
api/                    # routes: message_routes, contact_routes, shortcut_routes, health_routes
auth/                   # api_keys.py (store) + dependencies.py (require_scope)
services/
  chat_db.py            # read-only chat.db queries (unread/thread/style-context/verify_sent)
  typedstream.py        # attributedBody → text (post-Ventura text column is often NULL)
  ledger.py             # read-aloud ledger
  sender.py             # AppleScript send + post-send chat.db verification
  contacts.py           # pyobjc Contacts (graceful when unavailable/denied)
  shortcuts.py          # `shortcuts run` subprocess wrapper
  sanitize.py           # attachments → "[an image]", URLs → "[a link]"
config/settings.py      # env-overridable paths (CHAT_DB_PATH, OSX_API_DATA_DIR)
tests/                  # 88 tests, all runnable without TCC grants (fixture chat.db)
```

Env vars: `OSX_API_PORT` (7723), `SERVER_HOST`, `CHAT_DB_PATH`,
`OSX_API_DATA_DIR`, `JARVIS_APP_ID`/`JARVIS_APP_KEY` (log shipping only),
`JARVIS_CONFIG_URL` (+`_STYLE=external` under launchd). No database, no Redis,
no settings-DB — deliberately self-contained.

---

## Gotchas

- **TCC grants attach to the venv's python binary.** Rebuilding `.venv` or
  upgrading Python silently revokes FDA/Automation/Contacts. `/health` will
  show it (`messages_db: unreadable`), but remember: venv rebuild ⇒ redo the
  TCC ceremony.
- **Automation permission is not probeable** without triggering a real send —
  `/health` reports `automation: "unknown"`. Setup includes a one-time test
  send to yourself.
- **`attributedBody` decode is load-bearing.** Post-Ventura the `text` column
  is often NULL. `services/typedstream.py` is a minimal extractor, not a full
  typedstream parser — if Apple shifts the format, extend the fixtures in
  `tests/fixtures.py` with a real observed blob first.
- **Multi-user = N instances** (one Apple ID per macOS session). Speaker→
  instance binding lives in per-user command secrets on the node
  (`user_osx_api_instance_url` / `user_osx_api_api_key`), not in
  config-service.
- Tests run anywhere (fixture SQLite chat.db); anything needing real TCC
  grants (real Contacts, real sends) belongs in `tests/manual/` once added.
