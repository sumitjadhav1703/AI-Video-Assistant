"""Real durable reservations, confined to disposable loopback PostgreSQL schemas."""
import os
import unittest
import uuid
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from backend import db
from backend.core.provider_budget import (BUDGET_SCHEMA, JobBudgetExceeded, RouteQuotaExceeded,
    forecast_attempts, record_route_cooldown, reserve_attempt)
from backend.usage_limits import LimitExceeded


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'isolated loopback Postgres required')
class ProviderBudgetDatabaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['TEST_DATABASE_URL']
        if urlparse(cls.dsn).hostname not in ('127.0.0.1','localhost','::1'):
            raise ValueError('Tests refuse non-loopback databases')
        cls.schema = 'test_budget_' + uuid.uuid4().hex
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(f'CREATE SCHEMA {cls.schema}')
        cls.patcher = patch.object(db, 'connect', lambda: psycopg.connect(cls.dsn, row_factory=dict_row, options=f'-c search_path={cls.schema},public'))
        cls.patcher.start()
        with db.connect() as conn:
            conn.execute(db.SCHEMA.replace('CREATE EXTENSION IF NOT EXISTS vector;','') + BUDGET_SCHEMA)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def setUp(self):
        with db.connect() as conn:
            conn.execute('TRUNCATE provider_attempts,provider_operation_budgets,provider_route_cooldowns,transcript_chunks,jobs')
        self.route = SimpleNamespace(alias='test',provider='test',input_limit_tokens=4096,rpm=100,tpm=100000,rpd=1000)

    def test_parallel_last_operation_attempt_is_reserved_once(self):
        with db.connect() as conn:
            conn.execute("INSERT INTO provider_operation_budgets VALUES ('job',23,0,0)")
        def reserve(_):
            try:
                reserve_attempt('job', self.route, 10, 10)
                return True
            except JobBudgetExceeded:
                return False
        with ThreadPoolExecutor(max_workers=6) as executor:
            successes = list(executor.map(reserve, range(6)))
        self.assertEqual(sum(successes), 1)
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT attempts,input_tokens,output_tokens FROM provider_operation_budgets WHERE job_id='job'").fetchone(), {'attempts':24,'input_tokens':10,'output_tokens':10})
            self.assertEqual(conn.execute('SELECT COUNT(*) AS count FROM provider_attempts').fetchone()['count'], 1)

    def test_provider_rejection_rolls_back_and_job_deletion_preserves_usage(self):
        self.route.rpm = 1
        db.create_job('first','english')
        reserve_attempt('first',self.route,100,20)
        db.fail_job('first', 'synthetic failure')
        db.delete_job('first')
        with self.assertRaises(LimitExceeded):
            reserve_attempt('second',self.route,100,20)
        with db.connect() as conn:
            rows = conn.execute('SELECT job_id,attempts FROM provider_operation_budgets ORDER BY job_id').fetchall()
            self.assertEqual(rows,[{'job_id':'first','attempts':1}])
            self.assertEqual(conn.execute('SELECT COUNT(*) AS count FROM provider_attempts').fetchone()['count'],1)

    def test_context_rejection_never_reserves_and_ambiguous_failure_is_not_refunded(self):
        with self.assertRaises(ValueError):
            reserve_attempt('job',self.route,4096,1)
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS count FROM provider_attempts').fetchone()['count'],0)
        reserve_attempt('job',self.route,15,0)
        # No request outcome is required to retain a pessimistic reservation.
        with db.connect() as conn:
            self.assertEqual(conn.execute("SELECT attempts,input_tokens FROM provider_operation_budgets WHERE job_id='job'").fetchone(),{'attempts':1,'input_tokens':15})

    def test_paid_cap_is_atomic_and_survives_job_deletion(self):
        route = SimpleNamespace(alias='meta', provider='meta', model='meta/test', verified_free=False,
            input_limit_tokens=4096, rpm=100, tpm=100000, rpd=1000,
            input_price_per_million='1.25', output_price_per_million='4.25')
        db.create_job('paid', 'english')
        def reserve(_):
            try:
                reserve_attempt('paid', route, 100, 20)
                return True
            except RouteQuotaExceeded:
                return False
        with ThreadPoolExecutor(max_workers=6) as executor:
            self.assertEqual(sum(executor.map(reserve, range(6))), 1)
        db.fail_job('paid', 'synthetic failure')
        db.delete_job('paid')
        with self.assertRaises(RouteQuotaExceeded):
            reserve_attempt('paid', route, 100, 20)
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT estimated_cost FROM provider_attempts').fetchone()['estimated_cost'],
                             Decimal('0.000210'))

    def test_paid_job_and_daily_dollar_caps(self):
        route = SimpleNamespace(alias='meta', provider='meta', model='meta/test', verified_free=False,
            input_limit_tokens=10000, rpm=100, tpm=100000, rpd=1000,
            input_price_per_million='1.25', output_price_per_million='4.25')
        with self.assertRaises(RouteQuotaExceeded):
            reserve_attempt('too-expensive', route, 0, 2353)
        # Each reservation costs exactly one cent, even if its outcome is unknown.
        for index in range(5):
            reserve_attempt(f'job-{index}', route, 4600, 1000)
        with self.assertRaises(RouteQuotaExceeded):
            reserve_attempt('sixth', route, 1, 0)
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT SUM(estimated_cost) AS total FROM provider_attempts').fetchone()['total'], Decimal('0.05'))

    def test_paid_missing_or_underpriced_pricing_never_reserves(self):
        route = SimpleNamespace(alias='meta', provider='meta', model='meta/test', verified_free=False,
            input_limit_tokens=4096, rpm=100, tpm=100000, rpd=1000,
            input_price_per_million=None, output_price_per_million='4.25')
        for price in (None, '1.24'):
            route.input_price_per_million = price
            with self.assertRaises(ValueError):
                reserve_attempt('paid', route, 100, 20)
        with db.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) AS n FROM provider_attempts').fetchone()['n'], 0)

    def test_cooldown_and_forecast_choose_healthy_alternative(self):
        self.route.model = 'test/model'
        self.route.verified_free = True
        alternate = SimpleNamespace(alias='alt', provider='alt', model='alt/model', verified_free=True,
            input_limit_tokens=4096, rpm=100, tpm=100000, rpd=1000)
        record_route_cooldown(alternate, 60)
        result = forecast_attempts('job', [], generation_stages=[([alternate, self.route], 10, 10)] * 2)
        self.assertEqual(result['attempts'], 2)
        record_route_cooldown(self.route, 60)
        with self.assertRaises(RouteQuotaExceeded):
            reserve_attempt('job', self.route, 10, 10)
        with self.assertRaises(RouteQuotaExceeded):
            forecast_attempts('job', [], generation_stages=[([self.route, alternate], 10, 10)])

    def test_forecast_checks_each_mandatory_route_cooldown(self):
        alternate = SimpleNamespace(alias='alt', provider='test', model='alt/model', verified_free=True,
            input_limit_tokens=4096, rpm=100, tpm=100000, rpd=1000)
        record_route_cooldown(self.route, 60)
        with self.assertRaises(RouteQuotaExceeded):
            forecast_attempts('job', [(self.route, 10, 10), (alternate, 10, 10)])

    def test_forecast_counts_planned_usage_before_using_fallback(self):
        self.route.rpm = 1
        alternate = SimpleNamespace(alias='alt', provider='alt', model='alt/model', verified_free=True,
            input_limit_tokens=4096, rpm=1, tpm=100000, rpd=1000)
        stage = ([self.route, alternate], 10, 10)
        self.assertEqual(forecast_attempts('job', [], generation_stages=[stage, stage])['attempts'], 2)
        with self.assertRaises(RouteQuotaExceeded):
            forecast_attempts('job', [], generation_stages=[stage, stage, stage])
