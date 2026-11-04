"""Credential-safe health diagnostics; no real database or provider required."""
import logging
import unittest
from unittest.mock import AsyncMock, patch
from sqlalchemy.exc import OperationalError
from app.api.health import health_check
from app.db.database import log_connection_failure


class HealthLoggingTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_original_cause(self):
        original = ConnectionRefusedError('private_user private_password')
        try:
            raise TypeError('wrapper private_token') from original
        except TypeError as wrapped:
            with self.assertLogs('app.db.database', level=logging.ERROR) as logs:
                log_connection_failure(wrapped, operation='health_check')
            self.assertIs(wrapped.__cause__, original)
        self.assertEqual(logs.records[0].exception_type, 'ConnectionRefusedError')
        self.assertEqual(logs.records[0].exception_chain, ['TypeError', 'ConnectionRefusedError'])
        self.assertNotIn('private_', str(logs.output))

    async def test_real_asyncpg_keyword_typeerror(self):
        import asyncpg
        try:
            await asyncpg.connect(sslmode='require')
        except TypeError as original:
            with self.assertLogs('app.db.database', level=logging.ERROR) as logs:
                log_connection_failure(original, operation='health_check')
        else:
            self.fail('Expected unsupported asyncpg keyword')
        self.assertEqual(logs.records[0].exception_type, 'TypeError')
        self.assertIn("unsupported connection keyword 'sslmode'", logs.output[0])

    async def test_unknown_typeerror_redacts_all_payload(self):
        error = TypeError('postgresql://private_user:private_password@host/db token=private_token')
        error.__cause__ = error  # Defensive cycle handling.
        with self.assertLogs('app.db.database', level=logging.ERROR) as logs:
            log_connection_failure(error, operation='health_check')
        self.assertEqual(logs.records[0].exception_type, 'TypeError')
        self.assertNotIn('private_', str(logs.output))
        self.assertNotIn('postgresql://', str(logs.output))

    async def test_success(self):
        db = AsyncMock()
        with patch('app.api.health.check_redis_health', new=AsyncMock(return_value=True)), self.assertLogs('app.api.health', level=logging.INFO) as logs:
            result = await health_check(db)
        self.assertEqual(result.model_dump(), {'status':'ok', 'database':'connected', 'redis':'connected'})
        self.assertIn('postgresql_connection_succeeded', logs.output[0])
        self.assertEqual(str(db.execute.call_args.args[0]), 'SELECT 1')

    async def test_failure_is_sanitized(self):
        secret = 'postgresql://private_user:private_password@host/db?token=private_token'
        db = AsyncMock()
        db.execute.side_effect = OperationalError('SELECT 1', {}, ConnectionRefusedError(secret))
        with patch('app.api.health.check_redis_health', new=AsyncMock(return_value=True)), self.assertLogs('app.db.database', level=logging.ERROR) as logs:
            result = await health_check(db)
        self.assertEqual(result.model_dump(), {'status':'degraded', 'database':'disconnected', 'redis':'connected'})
        self.assertEqual(logs.records[0].exception_type, 'ConnectionRefusedError')
        self.assertIn('connection was refused', logs.output[0])
        self.assertNotIn('private_', str(logs.output))
        self.assertIsNone(logs.records[0].exc_info)
        db.rollback.assert_awaited_once()

    async def test_unknown_and_rollback_failure_are_safe(self):
        db = AsyncMock()
        db.execute.side_effect = RuntimeError('username=private_user password=private_password')
        db.rollback.side_effect = RuntimeError('private_token')
        with patch('app.api.health.check_redis_health', new=AsyncMock(return_value=True)), self.assertLogs('app.db.database', level=logging.ERROR) as logs:
            result = await health_check(db)
        self.assertEqual(result.database, 'disconnected')
        self.assertEqual(len(logs.records), 2)
        self.assertEqual(logs.records[1].operation, 'health_check_rollback')
        self.assertNotIn('private_', str(logs.output))


if __name__ == '__main__':
    unittest.main()
