import os
import unittest
import uuid
from unittest.mock import patch
from urllib.parse import urlparse
import psycopg
from psycopg.rows import dict_row
from backend import db
from test_hybrid import doc


@unittest.skipUnless(os.getenv('TEST_DATABASE_URL'),'isolated loopback Postgres required')
class StorageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dsn=os.environ['TEST_DATABASE_URL']
        if urlparse(cls.dsn).hostname not in ('127.0.0.1','localhost','::1'): raise ValueError('loopback required')
        cls.schema='test_storage_'+uuid.uuid4().hex
        with psycopg.connect(cls.dsn) as conn: conn.execute(f'CREATE SCHEMA {cls.schema}')
        cls.patcher=patch.object(db,'connect',lambda:psycopg.connect(cls.dsn,row_factory=dict_row,options=f'-c search_path={cls.schema},public'))
        cls.patcher.start()
        with db.connect() as conn: conn.execute(db.SCHEMA.replace('CREATE EXTENSION IF NOT EXISTS vector;',''))

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        with psycopg.connect(cls.dsn) as conn: conn.execute(f'DROP SCHEMA {cls.schema} CASCADE')

    def test_chunk_cascade_isolation_and_immutable_model(self):
        self.assertTrue(hasattr(db,'save_chunks'),'chunk storage missing')
        db.create_job('a','english');db.create_job('b','english')
        db.save_chunks('a',[doc(0,'alice')]);db.save_chunks('b',[doc(0,'bob','b')])
        self.assertEqual(db.load_chunks('a')[0].page_content,'alice')
        with self.assertRaises(ValueError):db.set_retrieval_config('a','hybrid-v1','other',768)
        with self.assertRaises(ValueError):db.save_chunks('a',[doc(1,'foreign','b')])
        db.delete_job_row('a')
        self.assertEqual(db.load_chunks('a'),[])
        self.assertEqual(db.load_chunks('b')[0].page_content,'bob')

    def test_legacy_is_retained_and_cannot_be_silently_switched(self):
        db.create_job('legacy','english')
        with db.connect() as conn: conn.execute("UPDATE jobs SET status='done',transcript='original' WHERE id='legacy'")
        with self.assertRaises(ValueError):db.save_chunks('legacy',[doc(0,'original','legacy')])
        self.assertEqual(db.get_job('legacy')['retrieval_version'],'legacy')
        self.assertEqual(db.get_job('legacy')['transcript'],'original')

    def test_partial_timestamps_reject_whole_corpus_without_switching_model(self):
        db.create_job('partial','english')
        partial = doc(0,'safe','partial')
        partial.metadata['end_ms'] = None
        with self.assertRaises(psycopg.errors.CheckViolation):
            db.save_chunks('partial',[partial])
        self.assertEqual(db.load_chunks('partial'),[])
        self.assertEqual(db.get_job('partial')['retrieval_version'],'legacy')
