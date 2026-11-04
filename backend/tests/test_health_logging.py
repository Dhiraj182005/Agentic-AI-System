"""Credential-safe health diagnostics; no real database or provider required."""
import logging
import unittest
from unittest.mock import AsyncMock, patch
from sqlalchemy.exc import OperationalError
from app.api.health import health_check


class HealthLoggingTests(unittest.IsolatedAsyncioTestCase):
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
