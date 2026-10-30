"""Staff account commands: create-user, disable-user, list-users (pilot v0.2).

    python tasks.py create-user --username asha --role operator
    echo "long password here" | python tasks.py create-user --username ravi --role officer --password-stdin
    python tasks.py disable-user --username ravi
    python tasks.py list-users
"""

import argparse
import getpass
import sys

from app import clock
from app.auth import ROLES
from app.models import UserAccount
from app.passwords import MIN_PASSWORD_LEN, hash_password
from app.routes.auth import normalize_username
from app.sessions import revoke_all_for_user


def _session():
    from app.db import get_session_factory
    from app.migrate import ensure_schema

    ensure_schema()
    return get_session_factory()()


def _read_password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    first = getpass.getpass(f"Password (at least {MIN_PASSWORD_LEN} characters): ")
    second = getpass.getpass("Repeat password: ")
    if first != second:
        raise SystemExit("Passwords do not match.")
    return first


def create_user(username: str, role: str, password: str) -> UserAccount:
    username = normalize_username(username)
    if not username or not username.replace("-", "").replace("_", "").replace(".", "").isalnum():
        raise ValueError("Username may use letters, digits, '.', '-' and '_' only.")
    if role not in ROLES:
        raise ValueError(f"Role must be one of: {', '.join(ROLES)}.")
    pw_hash = hash_password(password)
    with _session() as session:
        if session.query(UserAccount).filter_by(username=username).first():
            raise ValueError(f"User '{username}' already exists.")
        user = UserAccount(
            username=username,
            password_hash=pw_hash,
            role=role,
            active=True,
            created_at=clock.now_utc(),
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        session.expunge(user)
        return user


def disable_user(username: str) -> int:
    username = normalize_username(username)
    with _session() as session:
        user = session.query(UserAccount).filter_by(username=username).first()
        if user is None:
            raise ValueError(f"No user '{username}'.")
        user.active = False
        n = revoke_all_for_user(session, user.id)
        session.commit()
        return n


def list_users() -> list[tuple[str, str, bool]]:
    with _session() as session:
        return [
            (u.username, u.role, bool(u.active))
            for u in session.query(UserAccount).order_by(UserAccount.username).all()
        ]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    cmd, rest = argv[0], argv[1:]
    parser = argparse.ArgumentParser(prog=f"tasks.py {cmd}")
    try:
        if cmd == "create-user":
            parser.add_argument("--username", required=True)
            parser.add_argument("--role", required=True, choices=ROLES)
            parser.add_argument("--password-stdin", action="store_true")
            a = parser.parse_args(rest)
            user = create_user(a.username, a.role, _read_password(a.password_stdin))
            print(f"Created {user.role} '{user.username}'.")
        elif cmd == "disable-user":
            parser.add_argument("--username", required=True)
            a = parser.parse_args(rest)
            n = disable_user(a.username)
            print(f"Disabled '{normalize_username(a.username)}' and signed out {n} session(s).")
        elif cmd == "list-users":
            parser.parse_args(rest)
            rows = list_users()
            if not rows:
                print("No users yet. Create one with: python tasks.py create-user --username NAME --role operator")
            for username, role, active in rows:
                print(f"{username:<24} {role:<9} {'active' if active else 'disabled'}")
        else:
            print(f"Unknown command: {cmd}")
            return 1
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
