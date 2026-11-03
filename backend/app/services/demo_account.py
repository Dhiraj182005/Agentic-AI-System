"""Optional demo account for presentations.

Disabled by default. It is enabled only when DEMO_ACCOUNT_ENABLED=true and
both DEMO_ACCOUNT_EMAIL and DEMO_ACCOUNT_PASSWORD are set. The account is an
ordinary user (bcrypt-hashed password, normal JWT login, normal ownership
checks): it can only see the debates it creates itself.

The account is never created implicitly: run `python seed.py --demo` (or
`ensure_demo_account`) after configuring it. The public `/auth/demo`
endpoint only advertises credentials while the feature is enabled AND the
account exists, so a stale or half-configured setup hides the login button.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password, verify_password
from app.models.user import User
from app.services.auth_service import get_user_by_email

logger = logging.getLogger(__name__)

MIN_DEMO_PASSWORD_LENGTH = 8


class DemoAccountError(Exception):
    """The demo account is disabled or misconfigured."""


@dataclass(frozen=True)
class DemoCredentials:
    email: str
    password: str


def demo_credentials() -> DemoCredentials | None:
    """Configured demo credentials, or None when the feature is off."""
    settings = get_settings()
    if not settings.DEMO_ACCOUNT_ENABLED:
        return None
    email = (settings.DEMO_ACCOUNT_EMAIL or "").strip().lower()
    password = settings.DEMO_ACCOUNT_PASSWORD or ""
    if not email or len(password) < MIN_DEMO_PASSWORD_LENGTH:
        logger.warning(
            "DEMO_ACCOUNT_ENABLED is true but the demo email/password are "
            "missing or the password is shorter than %d characters; demo "
            "login stays disabled.",
            MIN_DEMO_PASSWORD_LENGTH,
        )
        return None
    return DemoCredentials(email=email, password=password)


def is_demo_email(email: str | None) -> bool:
    credentials = demo_credentials()
    return bool(credentials and email and email.strip().lower() == credentials.email)


async def available_demo_credentials(db: AsyncSession) -> DemoCredentials | None:
    """Credentials to show on the login page, only if the account exists."""
    credentials = demo_credentials()
    if credentials is None:
        return None
    if await get_user_by_email(db, credentials.email) is None:
        return None
    return credentials


async def ensure_demo_account(db: AsyncSession) -> User:
    """Create the demo user, or reset its password to the configured one.

    Raises DemoAccountError when the feature is disabled or misconfigured, so
    it can never create an account by accident.
    """
    credentials = demo_credentials()
    if credentials is None:
        raise DemoAccountError(
            "Demo account is disabled. Set DEMO_ACCOUNT_ENABLED=true, "
            "DEMO_ACCOUNT_EMAIL and DEMO_ACCOUNT_PASSWORD (min "
            f"{MIN_DEMO_PASSWORD_LENGTH} characters) first."
        )
    user = await get_user_by_email(db, credentials.email)
    if user is None:
        user = User(
            email=credentials.email,
            password_hash=hash_password(credentials.password),
        )
        db.add(user)
        logger.info("Created demo account %s", credentials.email)
    elif not verify_password(credentials.password, user.password_hash):
        user.password_hash = hash_password(credentials.password)
        logger.info("Reset demo account password for %s", credentials.email)
    await db.commit()
    await db.refresh(user)
    return user
