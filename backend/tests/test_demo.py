"""Demo account tests: disabled by default, explicit setup only, and login
always goes through the normal /auth/login endpoint and JWT checks."""

import asyncio
import contextlib
import unittest.mock

from app.core.config import Settings
from app.services.auth_service import get_user_by_email
from app.services.demo_account import DemoAccountError, ensure_demo_account
from tests import test_report as base

DEMO_EMAIL = "demo-presenter@example.com"
DEMO_PASSWORD = "demo-pass-1234"


@contextlib.contextmanager
def demo_settings(**overrides):
    values = {
        "DEMO_ACCOUNT_ENABLED": True,
        "DEMO_ACCOUNT_EMAIL": DEMO_EMAIL,
        "DEMO_ACCOUNT_PASSWORD": DEMO_PASSWORD,
    }
    values.update(overrides)
    settings = Settings(**values)
    with unittest.mock.patch(
        "app.services.demo_account.get_settings", return_value=settings
    ):
        yield settings


async def demo_info(client) -> dict:
    resp = await client.get("/api/v1/auth/demo")
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_disabled_by_default(client):
    with demo_settings(DEMO_ACCOUNT_ENABLED=False):
        body = await demo_info(client)
        assert body == {"enabled": False, "email": None, "password": None}
        async with base._test_session() as session:
            try:
                await ensure_demo_account(session)
                raise AssertionError("disabled demo account must not be created")
            except DemoAccountError:
                pass
            assert await get_user_by_email(session, DEMO_EMAIL) is None
    print("demo login disabled by default: PASSED")


async def test_misconfigured_or_missing_account_hidden(client):
    with demo_settings(DEMO_ACCOUNT_PASSWORD="short"):
        assert (await demo_info(client))["enabled"] is False
    with demo_settings(DEMO_ACCOUNT_EMAIL=""):
        assert (await demo_info(client))["enabled"] is False
    with demo_settings():
        # Enabled and configured, but the account has not been set up yet.
        assert (await demo_info(client))["enabled"] is False
    print("misconfigured or missing demo account stays hidden: PASSED")


async def test_demo_login_uses_normal_auth(client):
    with demo_settings():
        async with base._test_session() as session:
            user = await ensure_demo_account(session)
            assert user.password_hash != DEMO_PASSWORD, "password is hashed"
            again = await ensure_demo_account(session)
            assert again.id == user.id, "setup is idempotent"

        body = await demo_info(client)
        assert body == {"enabled": True, "email": DEMO_EMAIL, "password": DEMO_PASSWORD}

        resp = await client.post(
            "/api/v1/auth/login", json={"email": body["email"], "password": body["password"]}
        )
        assert resp.status_code == 200, resp.text
        token = resp.json()["access_token"]
        me = await client.get("/api/v1/auth/me", headers=base.auth(token))
        assert me.status_code == 200 and me.json()["is_demo"] is True

        bad = await client.post(
            "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": "wrong-password"}
        )
        assert bad.status_code == 401
        assert bad.json()["detail"] == "Incorrect email or password"

        regular = await base.register_and_login(client, base.unique_email("demo-regular"))
        me = await client.get("/api/v1/auth/me", headers=base.auth(regular))
        assert me.json()["is_demo"] is False

        # Ownership rules still apply to the demo account.
        debate_id = await base.create_debate(client, regular)
        resp = await client.get(f"/api/v1/debates/{debate_id}", headers=base.auth(token))
        assert resp.status_code == 404
        resp = await client.get(
            f"/api/v1/debates/{debate_id}/report.pdf", headers=base.auth(token)
        )
        assert resp.status_code == 404

    # Turning the feature off hides the credentials again; the flag goes too.
    with demo_settings(DEMO_ACCOUNT_ENABLED=False):
        assert (await demo_info(client))["enabled"] is False
        me = await client.get("/api/v1/auth/me", headers=base.auth(token))
        assert me.json()["is_demo"] is False
    print("demo login uses normal authentication: PASSED")


async def test_password_reset_on_setup(client):
    with demo_settings(DEMO_ACCOUNT_PASSWORD="rotated-pass-5678"):
        async with base._test_session() as session:
            await ensure_demo_account(session)
        resp = await client.post(
            "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": "rotated-pass-5678"}
        )
        assert resp.status_code == 200
        resp = await client.post(
            "/api/v1/auth/login", json={"email": DEMO_EMAIL, "password": DEMO_PASSWORD}
        )
        assert resp.status_code == 401, "old password no longer works after rotation"
    print("demo password rotation on setup: PASSED")


async def test_protected_routes_stay_protected(client):
    for path in ("/api/v1/auth/me", "/api/v1/debates", "/api/v1/analytics/summary"):
        resp = await client.get(path)
        assert resp.status_code == 401, (path, resp.status_code)
    print("protected routes stay protected: PASSED")


async def main():
    app = await base.setup()
    async with base.client_for(app) as client:
        await test_disabled_by_default(client)
        await test_misconfigured_or_missing_account_hidden(client)
        await test_demo_login_uses_normal_auth(client)
        await test_password_reset_on_setup(client)
        await test_protected_routes_stay_protected(client)
    await base.teardown()
    print("\nAll demo login tests PASSED!")


if __name__ == "__main__":
    asyncio.run(main())
