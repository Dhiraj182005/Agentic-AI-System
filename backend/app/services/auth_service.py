from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.schemas.auth import RegisterRequest


class AuthServiceError(Exception):
    pass


class DuplicateEmailError(AuthServiceError):
    pass


class InvalidCredentialsError(AuthServiceError):
    pass


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(
        select(User).where(User.email == email.lower().strip())
    )
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    try:
        parsed_id = UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        return None
    result = await db.execute(select(User).where(User.id == parsed_id))
    return result.scalar_one_or_none()


async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
    normalized_email = data.email.lower().strip()

    existing = await get_user_by_email(db, normalized_email)
    if existing is not None:
        raise DuplicateEmailError(normalized_email)

    user = User(email=normalized_email, password_hash=hash_password(data.password))
    db.add(user)
    try:
        await db.flush()
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise DuplicateEmailError(normalized_email) from None
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    normalized_email = email.lower().strip()
    user = await get_user_by_email(db, normalized_email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError(normalized_email)

    if not user.password_hash.startswith("bcrypt-sha256$"):
        user.password_hash = hash_password(password)
        await db.commit()
    return user
