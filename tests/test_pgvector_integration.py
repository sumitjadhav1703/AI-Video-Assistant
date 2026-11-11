"""Opt-in real pgvector test in a disposable loopback database and schema."""
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlparse

import psycopg
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_postgres import PGVector
from sqlalchemy import create_engine

from backend import db
from backend.core.vector_store import collection_for, delete_vector_store


class FixtureEmbeddings(Embeddings):
    def __init__(self, dimension):
        self.dimension = dimension

    def embed_documents(self, texts):
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text):
        return [1.0] + [0.0] * (self.dimension - 1)


@unittest.skipUnless(all(os.getenv(name) for name in ('TEST_DATABASE_URL', 'PGVECTOR_TEST_SQL_PATH', 'TESTPGVECTORLIB')),
                     'requires disposable loopback PostgreSQL and explicitly supplied local pgvector SQL/library')
class RealPGVectorTests(unittest.TestCase):
    def test_real_persistence_search_filter_mixed_dimensions_and_cleanup(self):
        dsn = os.environ['TEST_DATABASE_URL']
        if urlparse(dsn).hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Tests refuse non-loopback databases')
        sql_path = Path(os.environ['PGVECTOR_TEST_SQL_PATH']).resolve(strict=True)
        library = Path(os.environ['TESTPGVECTORLIB']).resolve(strict=True)
        schema = 'test_pgvector_' + uuid.uuid4().hex
        script = '\n'.join(line for line in sql_path.read_text().splitlines() if not line.startswith('\\'))
        script = script.replace('MODULE_PATHNAME', str(library).replace("'", "''"))
        engine = None
        try:
            with psycopg.connect(dsn) as conn:
                conn.execute(f'CREATE SCHEMA {schema}')
                conn.execute(f'SET search_path TO {schema}, public')
                conn.execute(script)
            engine = create_engine(dsn.replace('postgresql://', 'postgresql+psycopg://', 1),
                                   connect_args={'options': f'-c search_path={schema},public'})
            with patch.object(PGVector, 'create_vector_extension'):
                a = PGVector(embeddings=FixtureEmbeddings(768), collection_name=collection_for('a'), connection=engine)
                b = PGVector(embeddings=FixtureEmbeddings(768), collection_name=collection_for('b'), connection=engine)
                legacy = PGVector(embeddings=FixtureEmbeddings(1024), collection_name=collection_for('legacy'), connection=engine)
            a.add_documents([Document(id='a:0', page_content='owned', metadata={'job_id': 'a', 'chunk_id': 'a:0'}),
                             Document(id='foreign:0', page_content='foreign metadata', metadata={'job_id': 'b', 'chunk_id': 'foreign:0'})], ids=['a:0', 'foreign:0'])
            b.add_documents([Document(id='b:0', page_content='other job', metadata={'job_id': 'b', 'chunk_id': 'b:0'})], ids=['b:0'])
            legacy.add_documents([Document(id='legacy:0', page_content='legacy', metadata={'job_id': 'legacy'})], ids=['legacy:0'])
            with patch.object(PGVector, 'create_vector_extension'):
                reopened = PGVector(embeddings=FixtureEmbeddings(768), collection_name=collection_for('a'), connection=engine)
            self.assertEqual([d.id for d in reopened.similarity_search('q', k=10, filter={'job_id': 'a'})], ['a:0'])
            self.assertEqual([d.id for d in b.similarity_search('q', k=10, filter={'job_id': 'b'})], ['b:0'])
            self.assertEqual([d.id for d in legacy.similarity_search('q', k=10, filter={'job_id': 'legacy'})], ['legacy:0'])
            with patch.object(db, 'connect', new=lambda: psycopg.connect(dsn, options=f'-c search_path={schema},public', row_factory=psycopg.rows.dict_row)):
                delete_vector_store('a')
            self.assertEqual([d.id for d in b.similarity_search('q', k=10, filter={'job_id': 'b'})], ['b:0'])
            with psycopg.connect(dsn, options=f'-c search_path={schema},public') as conn:
                self.assertEqual(conn.execute('SELECT count(*) FROM langchain_pg_embedding').fetchone()[0], 2)
        finally:
            if engine is not None:
                engine.dispose()
            with psycopg.connect(dsn) as conn:
                conn.execute(f'DROP SCHEMA IF EXISTS {schema} CASCADE')


if __name__ == '__main__':
    unittest.main()
