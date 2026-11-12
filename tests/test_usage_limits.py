import importlib.util
import os
import unittest
from unittest.mock import patch


class UsageSettingsTests(unittest.TestCase):
    def test_guardrail_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('backend.usage_limits'))

    def test_defaults_and_blank_values_are_safe(self):
        from backend.usage_limits import Settings
        with patch.dict(os.environ, {'MAX_UPLOAD_MB': ''}, clear=True):
            settings = Settings.from_env()
        self.assertFalse(settings.provider_calls_enabled)
        self.assertEqual(settings.max_upload_bytes, 25 * 1024 * 1024)
        self.assertEqual(settings.jobs_per_ip_day, 1)
        self.assertEqual(settings.jobs_global_day, 5)

    def test_provider_enabled_requires_secret(self):
        from backend.usage_limits import Settings
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true'}, clear=True):
            with self.assertRaises(ValueError):
                Settings.from_env()

    def test_invalid_limits_do_not_disable_safety(self):
        from backend.usage_limits import Settings
        for value in ('0', '-1', 'oops'):
            with self.subTest(value=value), patch.dict(os.environ, {'MAX_UPLOAD_MB': value}, clear=True):
                with self.assertRaises(ValueError):
                    Settings.from_env()

    def test_identity_is_normalized_hmac_without_ip_disclosure(self):
        from backend.usage_limits import client_key
        secret = 's' * 32
        self.assertEqual(client_key('2001:0db8::1', secret), client_key('2001:db8::1', secret))
        key = client_key('127.0.0.1', secret)
        self.assertEqual(len(key), 64)
        self.assertNotIn('127.0.0.1', key)
        self.assertNotEqual(key, client_key('127.0.0.1', 't' * 32))
        with self.assertRaises(ValueError):
            client_key(None, secret)

    def test_provider_guard_disabled_and_sarvam_fail_closed(self):
        from backend.usage_limits import require_provider_calls
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                require_provider_calls()
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'true', 'RATE_LIMIT_SECRET': 's' * 32}, clear=True):
            require_provider_calls()
            with self.assertRaises(RuntimeError):
                require_provider_calls(sarvam=True)
