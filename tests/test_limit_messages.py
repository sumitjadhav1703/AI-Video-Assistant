import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend import db
from backend.core.provider_budget import RouteQuotaExceeded
from backend.usage_limits import PROVIDER_QUOTA_MESSAGE, LimitExceeded, Settings, limit_message

NOW = datetime(2026, 11, 17, 18, 0, tzinfo=timezone.utc)


class FakeCursor:
    """Answers _reserve's queries: the clock, then one counter row per limit, then the slot owner."""

    def __init__(self, counts, slot_owner=None):
        self.rows = [{'now': NOW}] + [{'count': c} for c in counts] + [{'owner_token': slot_owner}]

    def execute(self, *args):
        pass

    def fetchone(self):
        return self.rows.pop(0)


def settings():
    with patch.dict(os.environ, {}, clear=True):
        return Settings.from_env()


class LimitMessageTests(unittest.TestCase):
    def test_site_limit_explains_free_capacity_and_reset(self):
        with self.assertRaises(LimitExceeded) as raised:
            db._reserve(FakeCursor([0, 15]), 'processing', 'job', 'visitor', settings())
        message = str(raised.exception)
        self.assertIn('15 analyses a day', message)
        self.assertIn('midnight UTC', message)
        self.assertEqual(raised.exception.retry_after, 6 * 3600)

    def test_visitor_recording_and_busy_limits_say_which_one(self):
        with self.assertRaises(LimitExceeded) as visitor:
            db._reserve(FakeCursor([2]), 'processing', 'job', 'visitor', settings())
        self.assertIn('2 free analyses', str(visitor.exception))
        with self.assertRaises(LimitExceeded) as recording:
            db._reserve(FakeCursor([0, 0, 5]), 'chat', 'job', 'visitor', settings())
        self.assertIn('This recording has had its 5 free questions', str(recording.exception))
        with self.assertRaises(LimitExceeded) as busy:
            db._reserve(FakeCursor([0, 0], slot_owner='other'), 'processing', 'job', 'visitor', settings())
        self.assertIn("Another visitor's recording", str(busy.exception))
        self.assertEqual(busy.exception.retry_after, 60)

    def test_singular_counts_and_unknown_scopes(self):
        with patch.dict(os.environ, {'JOBS_PER_IP_DAY': '1'}, clear=True):
            self.assertIn('your 1 free analysis for', limit_message('jobs_ip_day', Settings.from_env()))
        self.assertEqual(str(LimitExceeded(5)), 'Demo usage limit reached. Please try again later.')
        self.assertEqual(limit_message('nope', settings()), 'Demo usage limit reached. Please try again later.')

    def test_provider_quota_uses_the_free_tier_message(self):
        self.assertEqual(str(RouteQuotaExceeded(60)), PROVIDER_QUOTA_MESSAGE)


if __name__ == '__main__':
    unittest.main()
