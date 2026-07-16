import os

import psycopg
from psycopg.rows import dict_row


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
    return psycopg.connect(get_database_url(), row_factory=dict_row)


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


def init_db() -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)
        conn.commit()


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
            "UPDATE jobs SET status='running', step=%s, updated_at=NOW() WHERE id=%s",
            (step, job_id),
        )
        conn.commit()


def fail_job(job_id: str, message: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET status='error', error=%s, updated_at=NOW() WHERE id=%s",
            (message, job_id),
        )
        conn.commit()


def finish_job(job_id: str, result: dict) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE jobs SET
                status='done', step='done', updated_at=NOW(),
                title=%s, transcript=%s, summary=%s,
                action_items=%s, key_decisions=%s, open_questions=%s
            WHERE id=%s
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
        conn.commit()


def get_job(job_id: str) -> dict | None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM jobs WHERE id=%s", (job_id,))
        return cur.fetchone()


def delete_job_row(job_id: str) -> None:
    with connect() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM jobs WHERE id=%s", (job_id,))
        conn.commit()


def job_ids_older_than(days: int) -> list[str]:
    """Ids of jobs created more than `days` ago — the cleanup sweep's work list."""
    with connect() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM jobs WHERE created_at < NOW() - make_interval(days => %s)",
            (days,),
        )
        return [row["id"] for row in cur.fetchall()]
