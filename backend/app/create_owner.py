import re
from getpass import getpass

from pwdlib import PasswordHash
from sqlalchemy.exc import IntegrityError

from app.auth_models import Owner
from app.database import SessionLocal


def main():
    with SessionLocal() as db:
        if db.get(Owner, 1):
            print("Owner account already exists.")
            return

    username = input("Choose username: ").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username):
        raise SystemExit(
            "Use 3–64 characters: letters, numbers, dots, underscores or hyphens."
        )

    password = getpass("Choose password (12–128 characters): ")
    if not 12 <= len(password) <= 128:
        raise SystemExit("Password must contain 12–128 characters.")

    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match. Run the command again.")

    hashed = PasswordHash.recommended().hash(password)

    with SessionLocal() as db:
        try:
            db.add(Owner(
                id=1,
                username=username,
                password_hash=hashed,
            ))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise SystemExit(
                "Account was not created. Check whether an owner already exists."
            )

    print(f"Owner account created: {username}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        raise SystemExit("\nCancelled.")