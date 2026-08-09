# jarvis-osx-api

macOS personal-data bridge for [Jarvis](https://github.com/alexberardi): read
and (with explicit approval) reply to iMessages by voice, resolve contacts, and
run Shortcuts — all local, no cloud.

- **Port:** 7723 · **Platform:** macOS only (native, never Docker)
- **Auth:** locally-minted scoped API keys (`python cli.py generate-api-key`)
- **Design doc:** `prds/osx-api.md` in the meta repo

## Setup

```bash
./run.sh                 # dev
./deploy-launchd.sh      # install as a LaunchAgent (production)
```

Then the one-time TCC ceremony (repeat after any venv rebuild — grants attach
to the venv's python binary):

1. **Full Disk Access** → add `.venv/bin/python` (for `~/Library/Messages/chat.db`)
2. **Automation** → first send prompts for Messages.app control; do a test send to yourself
3. **Contacts** → prompts on first `/v1/contacts/resolve`

Check `curl localhost:7723/health` — it reports each capability's TCC state.

## Tests

```bash
.venv/bin/python -m pytest -q
```

No Mac permissions needed — the suite runs against a fixture chat.db.
