from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
import hashlib
import base64

from app.core.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    # Prehash new passwords so bcrypt's 72-byte limit cannot silently discard
    # a suffix. Version the format; existing bcrypt hashes still authenticate.
    password_bytes = base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())
    salt = bcrypt.gensalt()
    return "bcrypt-sha256$" + bcrypt.hashpw(password_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith("bcrypt-sha256$"):
            password_bytes = base64.b64encode(hashlib.sha256(plain_password.encode("utf-8")).digest())
            return bcrypt.checkpw(password_bytes, password_hash.removeprefix("bcrypt-sha256$").encode("utf-8"))
        return bcrypt.checkpw(
            plain_password.encode("utf-8"), password_hash.encode("utf-8")
        )
    except (ValueError, TypeError):
        return False


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expires_minutes = expires_minutes or settings.ACCESS_TOKEN_EXPIRE_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_minutes)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> str | None:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
    except jwt.PyJWTError:
        return None
    subject = payload.get("sub")
    return subject if subject is not None else None
