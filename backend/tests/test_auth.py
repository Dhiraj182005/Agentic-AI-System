import asyncio

import httpx
from httpx import ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password

TEST_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/aidebate_test"

_test_engine = None
_test_session = None


async def setup():
    """Create a clean schema in the dedicated `aidebate_test` DB and override deps."""
    global _test_engine, _test_session

    _test_engine = create_async_engine(TEST_DB_URL)
    _test_session = async_sessionmaker(_test_engine, expire_on_commit=False)

    async with _test_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

    from app.db.database import Base
    import app.models  # noqa: F401  (register models)
    from app.models import User  # noqa: F401  (register User)

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.db.database import get_db
    from app.main import app

    async def override_get_db():
        async with _test_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    return app


async def teardown():
    from app.main import app

    app.dependency_overrides.clear()
    if _test_engine is not None:
        await _test_engine.dispose()


def client_for(app):
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


async def register(client, email, password):
    return await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )


async def login(client, email, password):
    return await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )


async def test_security_utilities():
    hashed = hash_password("super-secret-pass")
    assert hashed and hashed != "super-secret-pass"
    assert verify_password("super-secret-pass", hashed)
    assert not verify_password("wrong-pass", hashed)

    token = create_access_token(subject="some-user-id")
    assert decode_access_token(token) == "some-user-id"
    assert decode_access_token("garbage.token.value") is None
    print("security utilities: PASSED")


async def test_register_valid_user(client):
    resp = await register(client, "valid@example.com", "securepassword")
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["email"] == "valid@example.com"
    assert "id" in data
    assert "password_hash" not in data
    print("register valid user: PASSED")


async def test_password_is_hashed():
    from sqlalchemy import select

    from app.models.user import User

    async with _test_session() as db:
        result = await db.execute(select(User).where(User.email == "valid@example.com"))
        user = result.scalar_one_or_none()
        assert user is not None
        assert user.password_hash != "securepassword"
        assert verify_password("securepassword", user.password_hash)
    print("password hashed in DB (password != hash): PASSED")


async def test_register_duplicate_email(client):
    await register(client, "dup@example.com", "securepassword")
    resp = await register(client, "dup@example.com", "securepassword")
    assert resp.status_code == 409, resp.text
    print("register duplicate email (409): PASSED")


async def test_register_invalid_email(client):
    resp = await register(client, "not-an-email", "securepassword")
    assert resp.status_code == 422, resp.text
    print("register invalid email (422): PASSED")


async def test_register_invalid_password(client):
    resp = await register(client, "short@example.com", "short")
    assert resp.status_code == 422, resp.text
    print("register invalid password (422): PASSED")


async def test_login_correct_credentials(client):
    await register(client, "login@example.com", "securepassword")
    resp = await login(client, "login@example.com", "securepassword")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    print("login correct credentials: PASSED")


async def test_login_incorrect_password(client):
    await register(client, "badpw@example.com", "securepassword")
    resp = await login(client, "badpw@example.com", "wrongpassword")
    assert resp.status_code == 401, resp.text
    print("login incorrect password (401): PASSED")


async def test_login_unknown_email(client):
    resp = await login(client, "nobody@example.com", "securepassword")
    assert resp.status_code == 401, resp.text
    print("login unknown email (401): PASSED")


async def test_me_with_valid_token(client):
    await register(client, "me@example.com", "securepassword")
    token = (await login(client, "me@example.com", "securepassword")).json()["access_token"]
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["email"] == "me@example.com"
    assert "password_hash" not in data
    print("me with valid token: PASSED")


async def test_me_without_token(client):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401, resp.text
    print("me without token (401): PASSED")


async def test_me_with_invalid_token(client):
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.value"}
    )
    assert resp.status_code == 401, resp.text
    print("me with invalid token (401): PASSED")


async def test_me_with_expired_token(client):
    import jwt as _jwt

    settings = get_settings()
    expired = _jwt.encode(
        {"sub": "00000000-0000-0000-0000-000000000000", "exp": 0},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401, resp.text
    print("me with expired token (401): PASSED")


async def main():
    print("Setting up isolated test DB (aidebate_test)...")
    app = await setup()

    async with client_for(app) as client:
        await test_security_utilities()
        await test_register_valid_user(client)
        await test_password_is_hashed()
        await test_register_duplicate_email(client)
        await test_register_invalid_email(client)
        await test_register_invalid_password(client)
        await test_login_correct_credentials(client)
        await test_login_incorrect_password(client)
        await test_login_unknown_email(client)
        await test_me_with_valid_token(client)
        await test_me_without_token(client)
        await test_me_with_invalid_token(client)
        await test_me_with_expired_token(client)

    await teardown()
    print("\nAll authentication tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
