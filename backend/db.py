import os
import math
import uuid
from datetime import timedelta, timezone

from .usage_limits import Settings, LimitExceeded, JobUnavailable, JobBusy

import psycopg
from psycopg.rows import dict_row

_RECOVERY_MIN_AGE = timedelta(minutes=30)
INTERRUPTED_MESSAGE = 'Processing was interrupted. Start a new session and upload the file again or resubmit the URL.'


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set in environment / .env")
    return url


def get_sqlalchemy_url() -> str:
    """
    langchain-postgres talks to Postgres through SQLAlchemy and needs an explicit
    psycopg3 driver in the scheme. Neon hands out a plain postgresql:// URL, so
    rewrite the scheme without touching credentials or query params.
    """
    url = get_database_url()
    for prefix in ("postgresql+psycopg://", "postgres+psycopg://"):
        if url.startswith(prefix):
            return url
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    return url


def connect():
    return psycopg.connect(get_database_url(), row_factory=dict_row, connect_timeout=10,
                           options="-c statement_timeout=15000 -c lock_timeout=5000")


SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS jobs (
    id             TEXT PRIMARY KEY,
    status         TEXT NOT NULL,
    step           TEXT,
    error          TEXT,
    language       TEXT,
    title          TEXT,
    transcript     TEXT,
    summary        TEXT,
    action_items   TEXT,
    key_decisions  TEXT,
    open_questions TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


USAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_guard (
    id INTEGER PRIMARY KEY CHECK (id = 1)
);
INSERT INTO usage_guard (id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS usage_counters (
    bucket TIMESTAMPTZ NOT NULL,
    scope TEXT NOT NULL,
    subject TEXT NOT NULL,
    count BIGINT NOT NULL CHECK (count >= 0),
    PRIMARY KEY (bucket, scope, subject)
);
CREATE TABLE IF NOT EXISTS usage_slots (
    name TEXT PRIMARY KEY,
    owner_token TEXT,
    job_id TEXT,
    reserved_at TIMESTAMPTZ
);
ALTER TABLE usage_slots ADD COLUMN IF NOT EXISTS reserved_at TIMESTAMPTZ;
UPDATE usage_slots SET reserved_at=clock_timestamp() WHERE owner_token IS NOT NULL AND reserved_at IS NULL;
INSERT INTO usage_slots (name) VALUES ('processing'), ('chat') ON CONFLICT DO NOTHING;
"""
SCHEMA += USAGE_SCHEMA

SCHEMA += """
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS retrieval_version TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS embedding_model TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER;
CREATE TABLE IF NOT EXISTS transcript_chunks (
    chunk_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    text TEXT NOT NULL,
    start_ms BIGINT,
    end_ms BIGINT,
    timing_precision TEXT NOT NULL CHECK (timing_precision IN ('segment','piece','unknown')),
    UNIQUE (job_id, ordinal),
    CHECK ((start_ms IS NULL AND end_ms IS NULL AND timing_precision='unknown') OR
           (start_ms IS NOT NULL AND end_ms IS NOT NULL AND start_ms >= 0
            AND end_ms >= start_ms AND timing_precision <> 'unknown'))
);
CREATE INDEX IF NOT EXISTS transcript_chunks_job_id ON transcript_chunks(job_id);
"""


def init_db() -> None:
    from .core.provider_budget import BUDGET_SCHEMA
    from .core.audio_budget import AUDIO_SCHEMA
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA + BUDGET_SCHEMA + AUDIO_SCHEMA)
        conn.commit()


def _set_retrieval_config(cur, job_id, retrieval_version, embedding_model, embedding_dimension):
    cur.execute('SELECT status, retrieval_version, embedding_model, embedding_dimension FROM jobs WHERE id=%s FOR UPDATE', (job_id,))
    row = cur.fetchone()
    if not row:
        raise JobUnavailable('Job not found')
    requested = (retrieval_version, embedding_model, embedding_dimension)
    current = (row['retrieval_version'], row['embedding_model'], row['embedding_dimension'])
    if current != requested and (row['embedding_model'] is not None or row['status'] not in ('queued', 'running')):
        raise ValueError('Embedding configuration is immutable; legacy jobs require reprocessing.')
    if requested != ('hybrid-v1', 'gemini-embedding-001', 768):
        raise ValueError('Unsupported retrieval configuration')
    cur.execute('UPDATE jobs SET retrieval_version=%s, embedding_model=%s, embedding_dimension=%s WHERE id=%s', (*requested, job_id))


def set_retrieval_config(job_id, retrieval_version, embedding_model, embedding_dimension):
    with connect() as conn, conn.cursor() as cur:
        _set_retrieval_config(cur, job_id, retrieval_version, embedding_model, embedding_dimension)


def save_chunks(job_id, documents):
    from .core.guardrails import sanitize_text
    if not documents:
        raise ValueError('A chunk corpus cannot be empty')
    rows = []
    for ordinal, doc in enumerate(documents):
        metadata = doc.metadata
        chunk_id = f'{job_id}:{ordinal:06d}'
        if (metadata.get('job_id') != job_id or metadata.get('chunk_id') != chunk_id or
                metadata.get('ordinal') != ordinal or doc.id != chunk_id or
                not doc.page_content or sanitize_text(doc.page_content) != doc.page_content):
            raise ValueError('Chunk identity, order or sanitized text is invalid')
        rows.append((chunk_id, job_id, ordinal, doc.page_content,
                     metadata.get('start_ms'), metadata.get('end_ms'), metadata.get('timing_precision')))
    with connect() as conn, conn.cursor() as cur:
        _set_retrieval_config(cur, job_id, 'hybrid-v1', 'gemini-embedding-001', 768)
        cur.executemany('''INSERT INTO transcript_chunks (chunk_id,job_id,ordinal,text,start_ms,end_ms,timing_precision)
                           VALUES (%s,%s,%s,%s,%s,%s,%s)''', rows)


def load_chunks(job_id):
    from langchain_core.documents import Document
    with connect() as conn, conn.cursor() as cur:
        cur.execute('SELECT * FROM transcript_chunks WHERE job_id=%s ORDER BY ordinal,chunk_id', (job_id,))
        return [Document(id=row['chunk_id'], page_content=row['text'], metadata={
            'chunk_id': row['chunk_id'], 'job_id': row['job_id'], 'ordinal': row['ordinal'],
            'chunk_index': row['ordinal'], 'start_ms': row['start_ms'], 'end_ms': row['end_ms'],
            'timing_precision': row['timing_precision']}) for row in cur.fetchall()]


def create_job(job_id: str, language: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO jobs (id, status, step, language) VALUES (%s, 'queued', 'queued', %s)",
            (job_id, language),
        )
        conn.commit()


def set_step(job_id: str, step: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status='running', step=%s, updated_at=NOW() WHERE id=%s AND status IN ('queued', 'running')",
            (step, job_id),
        )
        if cur.rowcount != 1:
            raise JobUnavailable('Job is no longer active')
        conn.commit()


def fail_job(job_id: str, message: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status='error', error=%s, updated_at=NOW() WHERE id=%s AND status IN ('queued', 'running')",
            (message, job_id),
        )
        if cur.rowcount != 1:
            raise JobUnavailable('Job is no longer active')
        conn.commit()


def finish_job(job_id: str, result: dict) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs SET
                status='done', step='done', updated_at=NOW(),
                title=%s, transcript=%s, summary=%s,
                action_items=%s, key_decisions=%s, open_questions=%s
            WHERE id=%s AND status='running'
            """,
            (
                result["title"],
                result["transcript"],
                result["summary"],
                result["action_items"],
                result["key_decisions"],
                result["open_questions"],
                job_id,
            ),
        )
        if cur.rowcount != 1:
            raise JobUnavailable('Job is no longer active')
        conn.commit()


def get_job_status(job_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT id, status, step, error FROM jobs WHERE id=%s", (job_id,))
        return cur.fetchone()


def get_job(job_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
        return cur.fetchone()


def delete_job_row(job_id: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM jobs WHERE id=%s", (job_id,))
        conn.commit()


def job_ids_older_than(days: int) -> list[str]:
    """Terminal jobs untouched for at least `days`, excluding active reservations."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM jobs WHERE updated_at < NOW() - make_interval(days => %s)
               AND status IN ('done', 'error', 'interrupted')
               AND NOT EXISTS (SELECT 1 FROM usage_slots WHERE job_id=jobs.id AND owner_token IS NOT NULL)""",
            (days,),
        )
        return [row["id"] for row in cur.fetchall()]


def _lock_admission(cur):
    cur.execute("SELECT id FROM usage_guard WHERE id=1 FOR UPDATE")
    if cur.fetchone() is None:
        raise RuntimeError('Usage guard is missing')


def _reserve(cur, slot: str, job_id: str, identity: str, settings: Settings) -> str:
    # Use the database clock and UTC boundaries, independent of the host timezone.
    cur.execute("SELECT clock_timestamp() AS now")
    now = cur.fetchone()['now'].astimezone(timezone.utc)
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    minute = now.replace(second=0, microsecond=0)
    if slot == 'processing':
        limits = [(day, 'jobs_ip_day', identity, settings.jobs_per_ip_day, 86400),
                  (day, 'jobs_global_day', '*', settings.jobs_global_day, 86400)]
    else:
        limits = [(minute, 'chats_ip_minute', identity, settings.chats_per_ip_minute, 60),
                  (day, 'chats_ip_day', identity, settings.chats_per_ip_day, 86400),
                  (day, 'chats_job_day', job_id, settings.chats_per_job_day, 86400),
                  (day, 'chats_global_day', '*', settings.chats_global_day, 86400)]
    for bucket, scope, subject, ceiling, seconds in limits:
        cur.execute("SELECT count FROM usage_counters WHERE bucket=%s AND scope=%s AND subject=%s",
                    (bucket, scope, subject))
        row = cur.fetchone()
        if row and row['count'] >= ceiling:
            raise LimitExceeded(math.ceil((bucket + timedelta(seconds=seconds) - now).total_seconds()))
    cur.execute("SELECT owner_token FROM usage_slots WHERE name=%s", (slot,))
    row = cur.fetchone()
    if row is None:
        raise RuntimeError('Usage slot is missing')
    if row['owner_token'] is not None:
        raise LimitExceeded(60)
    # Retain current and recent buckets; this never refunds today's usage.
    cur.execute("DELETE FROM usage_counters WHERE bucket < %s", (day - timedelta(days=2),))
    token = uuid.uuid4().hex
    for bucket, scope, subject, _, _ in limits:
        cur.execute("""INSERT INTO usage_counters (bucket, scope, subject, count) VALUES (%s,%s,%s,1)
                       ON CONFLICT (bucket,scope,subject) DO UPDATE SET count=usage_counters.count+1""",
                    (bucket, scope, subject))
    cur.execute("UPDATE usage_slots SET owner_token=%s, job_id=%s, reserved_at=clock_timestamp() WHERE name=%s",
                (token, job_id, slot))
    return token


def admit_job(job_id: str, language: str, identity: str, settings: Settings) -> str:
    with connect() as conn, conn.cursor() as cur:
        _lock_admission(cur)
        token = _reserve(cur, 'processing', job_id, identity, settings)
        cur.execute("INSERT INTO jobs (id,status,step,language) VALUES (%s,'queued','queued',%s)", (job_id, language))
        return token


def reserve_chat(job_id: str, identity: str, settings: Settings) -> str:
    with connect() as conn, conn.cursor() as cur:
        _lock_admission(cur)
        cur.execute("SELECT status FROM jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            raise JobUnavailable('Job not found')
        if row['status'] != 'done':
            raise JobBusy('Job is not ready')
        return _reserve(cur, 'chat', job_id, identity, settings)


def release_slot(name: str, token: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE usage_slots SET owner_token=NULL, job_id=NULL, reserved_at=NULL WHERE name=%s AND owner_token=%s",
                    (name, token))


def inspect_slots() -> list[dict]:
    """Private operator diagnostics for occupied reservations."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT s.name, s.owner_token, s.job_id, s.reserved_at, j.status AS job_status, j.step, j.updated_at,
                      s.reserved_at IS NOT NULL AND
                          GREATEST(s.reserved_at, CASE WHEN s.name='processing' THEN j.updated_at END)
                              <= clock_timestamp() - %s AS stale
               FROM usage_slots s LEFT JOIN jobs j ON j.id=s.job_id
               WHERE s.owner_token IS NOT NULL ORDER BY s.name""",
            (_RECOVERY_MIN_AGE,),
        )
        return cur.fetchall()


def recover_slot(name: str, token: str, *, all_workers_stopped: bool) -> None:
    """Release one stale reservation after an operator confirms worker shutdown."""
    if all_workers_stopped is not True:
        raise ValueError('Stop all workers that could still own the reservation before recovery.')
    if name not in ('processing', 'chat') or not token:
        raise ValueError('An exact slot name and owner token are required.')
    with connect() as conn, conn.cursor() as cur:
        _lock_admission(cur)
        cur.execute(
            """SELECT job_id, reserved_at <= clock_timestamp() - %s AS stale
               FROM usage_slots WHERE name=%s AND owner_token=%s FOR UPDATE""",
            (_RECOVERY_MIN_AGE, name, token),
        )
        reservation = cur.fetchone()
        if reservation is None:
            raise ValueError('The slot no longer has that owner token.')
        if not reservation['stale']:
            raise ValueError('The reservation is not stale. Wait at least 30 minutes from reservation.')

        if name == 'processing':
            job_id = reservation['job_id']
            cur.execute("SELECT updated_at > clock_timestamp() - %s AS recent FROM jobs WHERE id=%s FOR UPDATE",
                        (_RECOVERY_MIN_AGE, job_id))
            job = cur.fetchone()
            if job and job['recent']:
                raise ValueError('The job has recent progress. Wait at least 30 minutes from the latest update.')
            cur.execute(
                """UPDATE jobs SET status='interrupted', error=%s, updated_at=clock_timestamp()
                   WHERE id=%s AND status IN ('queued', 'running')""",
                (INTERRUPTED_MESSAGE, job_id),
            )
        cur.execute("UPDATE usage_slots SET owner_token=NULL, job_id=NULL, reserved_at=NULL WHERE name=%s AND owner_token=%s",
                    (name, token))


def begin_delete(job_id: str) -> str:
    with connect() as conn, conn.cursor() as cur:
        _lock_admission(cur)
        cur.execute("SELECT status FROM jobs WHERE id=%s", (job_id,))
        row = cur.fetchone()
        if not row:
            raise JobUnavailable('Job not found')
        cur.execute("SELECT 1 FROM usage_slots WHERE job_id=%s AND owner_token IS NOT NULL", (job_id,))
        if row['status'] in ('queued', 'running', 'deleting') or cur.fetchone():
            raise JobBusy('Job is active')
        cur.execute("UPDATE jobs SET status='deleting', updated_at=NOW() WHERE id=%s", (job_id,))
        return row['status']


def restore_after_delete_error(job_id: str, previous_status: str, message: str | None = None) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("UPDATE jobs SET status=%s, error=COALESCE(%s,error), updated_at=NOW() WHERE id=%s AND status='deleting'", (previous_status, message, job_id))
