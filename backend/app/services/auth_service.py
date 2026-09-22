from sqlalchemy import select
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
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def register_user(db: AsyncSession, data: RegisterRequest) -> User:
    normalized_email = data.email.lower().strip()

    existing = await get_user_by_email(db, normalized_email)
    if existing is not None:
        raise DuplicateEmailError(normalized_email)

    user = User(email=normalized_email, password_hash=hash_password(data.password))
    db.add(user)
    await db.flush()
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, email: str, password: str) -> User:
    normalized_email = email.lower().strip()
    user = await get_user_by_email(db, normalized_email)
    if user is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError(normalized_email)
    return user
