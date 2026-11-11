"""Opt-in collection cleanup test against an isolated loopback PostgreSQL schema."""
import os
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row

from backend import db
from backend.core.vector_store import delete_vector_store


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'), 'set TEST_DATABASE_URL to an isolated local PostgreSQL')
class VectorCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn = os.environ['TEST_DATABASE_URL']
        if urlparse(cls.dsn).hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Tests refuse non-loopback databases')
        cls.schema = 'test_vectors_' + uuid.uuid4().hex
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(f'CREATE SCHEMA {cls.schema}')
        cls.connection_patch = patch.object(
            db, 'connect', new=lambda: psycopg.connect(
                cls.dsn, row_factory=dict_row, options=f'-c search_path={cls.schema}'
            ),
        )
        cls.connection_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.connection_patch.stop()
        with psycopg.connect(cls.dsn) as conn:
            conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def test_delete_cascades_only_to_matching_job_and_handles_absence(self):
        with db.connect() as conn:
            conn.execute('CREATE TABLE langchain_pg_collection (uuid TEXT PRIMARY KEY, name TEXT UNIQUE)')
            conn.execute('CREATE TABLE langchain_pg_embedding (id TEXT PRIMARY KEY, collection_id TEXT REFERENCES langchain_pg_collection(uuid) ON DELETE CASCADE, document TEXT)')
            conn.execute("INSERT INTO langchain_pg_collection VALUES ('a', 'job_a'), ('b', 'job_b')")
            conn.execute("INSERT INTO langchain_pg_embedding VALUES ('one', 'a', 'a'), ('two', 'b', 'b')")
        with patch.dict(os.environ, {'ENABLE_PROVIDER_CALLS': 'false'}):
            delete_vector_store('a')
            delete_vector_store('a')
            with db.connect() as conn:
                self.assertEqual(conn.execute('SELECT name FROM langchain_pg_collection').fetchall(), [{'name': 'job_b'}])
                self.assertEqual(conn.execute('SELECT id FROM langchain_pg_embedding').fetchall(), [{'id': 'two'}])
                conn.execute('DROP TABLE langchain_pg_embedding, langchain_pg_collection')
            delete_vector_store('absent')


if __name__ == '__main__':
    unittest.main()
