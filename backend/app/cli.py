"""Operator commands. Password input is not echoed and is not logged."""

from __future__ import annotations

import argparse
import getpass

from app.config import load_settings, validate_limits
from app.db import connect, init_db
from app.security import operator_exists, revoke_all_sessions, set_password


def main() -> None:
    parser = argparse.ArgumentParser(prog="seorap")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("bootstrap", help="Set the initial local password")
    sub.add_parser("reset-password", help="Replace the password and revoke sessions")
    args = parser.parse_args()
    settings = load_settings()
    validate_limits(settings)
    init_db(settings).close()
    conn = connect(settings)
    try:
        if args.command == "bootstrap":
            if operator_exists(conn):
                raise SystemExit("A password is already set. Use reset-password.")
            _set(conn)
            print("Password set. Existing sessions: none.")
        elif args.command == "reset-password":
            if not operator_exists(conn):
                raise SystemExit("No password yet. Use bootstrap.")
            _set(conn)
            revoke_all_sessions(conn)
            print("Password replaced. Existing sessions were revoked.")
    finally:
        conn.close()


def _set(conn) -> None:
    password = getpass.getpass("Local password: ")
    confirm = getpass.getpass("Confirm password: ")
    if password != confirm:
        raise SystemExit("Passwords did not match.")
    set_password(conn, password)


if __name__ == "__main__":
    main()
