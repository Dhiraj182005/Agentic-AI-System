"""Production safety, password compatibility, auth input and fixture guards."""
import asyncio
import bcrypt
from pydantic import ValidationError
from app.core.config import Settings
from app.core.security import hash_password, verify_password, create_access_token
from tests import require_disposable_database
from tests import test_auth as base


def test_production_configuration():
    options = dict(_env_file=None, APP_ENV='production', JWT_SECRET_KEY='a' * 48,
        FRONTEND_URL='https://maves.example.com',
        DATABASE_URL='postgresql+asyncpg://maves:random-test-password@db/maves',
        REDIS_URL='redis://:random-test-password@redis/0', DEMO_ACCOUNT_ENABLED=False)
    assert Settings(**options).APP_ENV == 'production'
    for changes in ({'JWT_SECRET_KEY': 'change-me'}, {'FRONTEND_URL': '*'},
                    {'FRONTEND_URL': 'http://localhost:5173'}, {'DEMO_ACCOUNT_ENABLED': True},
                    {'DATABASE_URL': 'postgresql+asyncpg://postgres:postgres@db/aidebate'},
                    {'REDIS_URL': 'redis://redis:6379/0'}, {'JWT_ALGORITHM': 'none'}):
        try:
            Settings(**dict(options, **changes))
        except ValidationError as exc:
            assert options['DATABASE_URL'] not in str(exc), 'Configuration errors must hide input credentials'
        else:
            raise AssertionError(f'Unsafe production configuration accepted: {list(changes)}')
    print('Production fails closed on insecure defaults and hides validation inputs: PASSED')


def test_password_formats():
    first, second = 'a' * 72 + 'first', 'a' * 72 + 'second'
    hashed = hash_password(first)
    assert verify_password(first, hashed) and not verify_password(second, hashed)
    unicode_password = 'ü' * 100
    assert verify_password(unicode_password, hash_password(unicode_password))
    old = bcrypt.hashpw(b'legacy-password', bcrypt.gensalt()).decode()
    assert verify_password('legacy-password', old)
    print('Full-length and Unicode passwords retain suffixes; legacy bcrypt remains valid: PASSED')


def test_fixture_guard():
    require_disposable_database('postgresql+asyncpg://local/maves_audit_test_new')
    for name in ('aidebate', 'postgres', 'aidebate_test', 'production'):
        try:
            require_disposable_database(f'postgresql+asyncpg://local/{name}')
        except RuntimeError:
            pass
        else:
            raise AssertionError('Non-disposable database must be rejected')
    print('Direct destructive fixtures reject application and generic database names: PASSED')


async def main():
    test_production_configuration()
    test_password_formats()
    test_fixture_guard()
    app = await base.setup()
    async with base.client_for(app) as client:
        for subject in ('not-a-uuid', '1234', ''):
            token = create_access_token(subject)
            response = await client.get('/api/v1/auth/me', headers={'Authorization': f'Bearer {token}'})
            assert response.status_code == 401
    await base.teardown()
    print('Malformed signed JWT subjects return 401 without database conversion errors: PASSED')


if __name__ == '__main__':
    asyncio.run(main())
