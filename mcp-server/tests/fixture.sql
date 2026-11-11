-- Synthetic local fixture only. Production grants and deployment require separate review.
CREATE ROLE ava_mcp_fixture_owner NOLOGIN;
CREATE ROLE ava_mcp_fixture_reader NOLOGIN;
CREATE SCHEMA ava_mcp_fixture_base;
CREATE SCHEMA ava_mcp_preview;
CREATE TABLE ava_mcp_fixture_base.jobs (
  id text PRIMARY KEY, status text NOT NULL, step text, retrieval_version text NOT NULL,
  created_at timestamptz NOT NULL, title text, summary text, action_items text,
  key_decisions text, open_questions text
);
CREATE TABLE ava_mcp_fixture_base.shares (
  job_id text PRIMARY KEY REFERENCES ava_mcp_fixture_base.jobs(id) ON DELETE CASCADE,
  public_id uuid UNIQUE NOT NULL, content_approved boolean NOT NULL DEFAULT false,
  CHECK (public_id::text <> job_id)
);
CREATE TABLE ava_mcp_fixture_base.transcript_chunks (
  job_id text NOT NULL REFERENCES ava_mcp_fixture_base.jobs(id) ON DELETE CASCADE,
  ordinal integer NOT NULL, text text NOT NULL, start_ms bigint, end_ms bigint,
  timing_precision text NOT NULL, PRIMARY KEY (job_id, ordinal)
);
GRANT USAGE ON SCHEMA ava_mcp_fixture_base TO ava_mcp_fixture_owner;
GRANT SELECT (id, status, step, retrieval_version, created_at, title, summary, action_items, key_decisions, open_questions)
  ON ava_mcp_fixture_base.jobs TO ava_mcp_fixture_owner;
GRANT SELECT (job_id, public_id, content_approved) ON ava_mcp_fixture_base.shares TO ava_mcp_fixture_owner;
GRANT SELECT (job_id, ordinal, text, start_ms, end_ms, timing_precision)
  ON ava_mcp_fixture_base.transcript_chunks TO ava_mcp_fixture_owner;
GRANT CREATE ON SCHEMA ava_mcp_preview TO ava_mcp_fixture_owner;
CREATE VIEW ava_mcp_preview.shared_jobs WITH (security_barrier = true) AS
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
FROM ava_mcp_fixture_base.jobs j JOIN ava_mcp_fixture_base.shares s ON s.job_id = j.id
WHERE j.status <> 'deleting';
CREATE VIEW ava_mcp_preview.shared_chunks WITH (security_barrier = true) AS
SELECT s.public_id AS job_id, c.ordinal, left(c.text, 500) AS text,
       c.start_ms, c.end_ms, c.timing_precision
FROM ava_mcp_fixture_base.transcript_chunks c
JOIN ava_mcp_fixture_base.jobs j ON j.id = c.job_id
JOIN ava_mcp_fixture_base.shares s ON s.job_id = j.id
WHERE s.content_approved AND j.status = 'done' AND j.retrieval_version = 'hybrid-v1';
ALTER VIEW ava_mcp_preview.shared_jobs OWNER TO ava_mcp_fixture_owner;
ALTER VIEW ava_mcp_preview.shared_chunks OWNER TO ava_mcp_fixture_owner;
REVOKE CREATE ON SCHEMA ava_mcp_preview FROM ava_mcp_fixture_owner;
GRANT USAGE ON SCHEMA ava_mcp_preview TO ava_mcp_fixture_reader;
GRANT SELECT ON ava_mcp_preview.shared_jobs, ava_mcp_preview.shared_chunks TO ava_mcp_fixture_reader;
ALTER ROLE ava_mcp_fixture_reader SET statement_timeout = '2s';
