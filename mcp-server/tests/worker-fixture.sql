-- Local CI database only. Apply after fixture.sql.
ALTER ROLE ava_mcp_fixture_reader LOGIN PASSWORD 'ci_reader_only';

INSERT INTO ava_mcp_fixture_base.jobs
  (id, status, step, retrieval_version, created_at, title, summary)
VALUES ('fixture-video', 'done', 'done', 'hybrid-v1', now(), 'Fixture video', 'Synthetic summary.'),
       ('fixture-legacy', 'done', 'done', 'legacy', now(), 'Fixture legacy video', 'Synthetic legacy summary.');

INSERT INTO ava_mcp_fixture_base.shares (job_id, public_id, content_approved)
VALUES ('fixture-video', '00000000-0000-4000-8000-000000000001', true),
       ('fixture-legacy', '00000000-0000-4000-8000-000000000002', true);

INSERT INTO ava_mcp_fixture_base.transcript_chunks
VALUES ('fixture-video', 0, 'Synthetic transcript excerpt.', 0, 1000, 'segment'),
       ('fixture-video', 1, 'Another synthetic excerpt.', NULL, NULL, 'unknown');
