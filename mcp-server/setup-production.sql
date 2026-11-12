-- One-time setup for a fresh sample database after the backend has initialized its schema.
-- Run with psql as the approved owner of the application tables.
\set ON_ERROR_STOP on
BEGIN;

CREATE ROLE ava_mcp_view_owner NOLOGIN;
CREATE ROLE ava_mcp_reader NOLOGIN;
GRANT ava_mcp_view_owner TO CURRENT_USER WITH SET TRUE;

CREATE SCHEMA ava_mcp;
REVOKE ALL ON SCHEMA ava_mcp FROM PUBLIC;
CREATE TABLE ava_mcp.shares (
  job_id text PRIMARY KEY REFERENCES public.jobs(id) ON DELETE CASCADE,
  public_id uuid UNIQUE NOT NULL DEFAULT gen_random_uuid(),
  content_approved boolean NOT NULL DEFAULT false,
  CHECK (public_id::text <> job_id)
);

GRANT USAGE ON SCHEMA public TO ava_mcp_view_owner;
GRANT USAGE, CREATE ON SCHEMA ava_mcp TO ava_mcp_view_owner;
GRANT SELECT (id, status, step, retrieval_version, created_at, title, summary, action_items, key_decisions, open_questions)
  ON public.jobs TO ava_mcp_view_owner;
GRANT SELECT (job_id, ordinal, text, start_ms, end_ms, timing_precision)
  ON public.transcript_chunks TO ava_mcp_view_owner;
GRANT SELECT (job_id, public_id, content_approved) ON ava_mcp.shares TO ava_mcp_view_owner;

SET LOCAL ROLE ava_mcp_view_owner;
CREATE VIEW ava_mcp.shared_jobs WITH (security_barrier = true) AS
SELECT s.public_id AS job_id, j.status,
       CASE WHEN j.step IN ('audio','transcript','title','summary','extract','rag','done') THEN j.step END AS step,
       CASE j.status WHEN 'error' THEN 'PROCESSING_FAILED' WHEN 'interrupted' THEN 'PROCESSING_INTERRUPTED' END AS error_code,
       j.created_at, CASE WHEN s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1' THEN left(j.title, 200) END AS title,
       (s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1') AS content_available,
       CASE WHEN s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1' THEN left(j.summary, 1500) END AS summary,
       CASE WHEN s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1' THEN left(j.action_items, 750) END AS action_items,
       CASE WHEN s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1' THEN left(j.key_decisions, 750) END AS key_decisions,
       CASE WHEN s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1' THEN left(j.open_questions, 750) END AS open_questions,
       CASE WHEN s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1' THEN array_remove(ARRAY[
         CASE WHEN length(j.title) > 200 THEN 'title' END,
         CASE WHEN length(j.summary) > 1500 THEN 'summary' END,
         CASE WHEN length(j.action_items) > 750 THEN 'action_items' END,
         CASE WHEN length(j.key_decisions) > 750 THEN 'key_decisions' END,
         CASE WHEN length(j.open_questions) > 750 THEN 'open_questions' END], NULL) ELSE ARRAY[]::text[] END AS truncated_fields
FROM public.jobs j JOIN ava_mcp.shares s ON s.job_id = j.id
WHERE j.status <> 'deleting';
CREATE VIEW ava_mcp.shared_chunks WITH (security_barrier = true) AS
SELECT s.public_id AS job_id, c.ordinal, left(c.text, 500) AS text,
       c.start_ms, c.end_ms, c.timing_precision
FROM public.transcript_chunks c
JOIN public.jobs j ON j.id = c.job_id
JOIN ava_mcp.shares s ON s.job_id = j.id
WHERE s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1';
GRANT SELECT ON ava_mcp.shared_jobs, ava_mcp.shared_chunks TO ava_mcp_reader;
RESET ROLE;

REVOKE CREATE ON SCHEMA ava_mcp FROM ava_mcp_view_owner;
GRANT USAGE ON SCHEMA ava_mcp TO ava_mcp_reader;
SELECT format('GRANT CONNECT ON DATABASE %I TO ava_mcp_reader', current_database()) \gexec
ALTER ROLE ava_mcp_reader SET statement_timeout = '2s';

COMMIT;
