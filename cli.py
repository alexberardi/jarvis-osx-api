"""Admin CLI for API keys (PRD decision #3 — keys are minted locally).

Usage:
  python cli.py generate-api-key --scopes messages:read,contacts:read [--name kitchen-node]
  python cli.py list-api-keys
  python cli.py revoke-api-key <key_id>

The raw key is printed exactly once and never stored.
"""

import argparse
import sys
from datetime import datetime, timezone

from auth.api_keys import VALID_SCOPES, ApiKeyStore, InvalidScopeError


def _generate(args: argparse.Namespace) -> int:
    scopes = [s.strip() for s in args.scopes.split(",") if s.strip()]
    try:
        raw, key = ApiKeyStore().generate(scopes, name=args.name)
    except InvalidScopeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"API key (shown once, store it now):\n\n  {raw}\n")
    print(f"id:     {key.key_id}")
    print(f"name:   {key.name or '-'}")
    print(f"scopes: {', '.join(key.scopes)}")
    return 0


def _list(_args: argparse.Namespace) -> int:
    keys = ApiKeyStore().list_keys()
    if not keys:
        print("no API keys")
        return 0
    for key in keys:
        created = datetime.fromtimestamp(key.created_at, tz=timezone.utc).strftime("%Y-%m-%d")
        print(f"{key.key_id}  {created}  {key.name or '-':20}  {', '.join(key.scopes)}")
    return 0


def _revoke(args: argparse.Namespace) -> int:
    if ApiKeyStore().revoke(args.key_id):
        print(f"revoked {args.key_id}")
        return 0
    print(f"error: no key with id {args.key_id}", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis-osx-api")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate-api-key", help="mint a scoped bearer key")
    gen.add_argument("--scopes", required=True, help=f"comma-separated; valid: {', '.join(sorted(VALID_SCOPES))}")
    gen.add_argument("--name", default=None, help="label, e.g. which node/user holds it")
    gen.set_defaults(func=_generate)

    lst = sub.add_parser("list-api-keys", help="list keys (never shows raw values)")
    lst.set_defaults(func=_list)

    rev = sub.add_parser("revoke-api-key", help="revoke by key id")
    rev.add_argument("key_id")
    rev.set_defaults(func=_revoke)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
