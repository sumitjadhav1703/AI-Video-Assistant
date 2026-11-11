import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { randomBytes } from 'node:crypto';
import { isCallToolResult, isJSONRPCResultResponse, WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/server';
import { Client } from 'pg';
import { createReader } from '../src/db.ts';
import { createServer } from '../src/tools.ts';

const url = process.env.TEST_DATABASE_URL;

test('isolated view permissions and reader behavior', { skip: !url }, async () => {
  const parsed = new URL(url!);
  assert.ok(['postgres:', 'postgresql:'].includes(parsed.protocol));
  assert.ok(['127.0.0.1', '[::1]'].includes(parsed.hostname));
  assert.equal(parsed.search + parsed.hash, '', 'use a direct loopback DSN without overrides');
  assert.equal(parsed.pathname, '/ava_mcp_test');
  const admin = new Client({ connectionString: url, connectionTimeoutMillis: 5000 });
  await admin.connect();
  let created = false;
  try {
    const existing = await admin.query(`SELECT EXISTS (SELECT FROM pg_roles WHERE rolname IN ('ava_mcp_fixture_owner','ava_mcp_fixture_reader')) OR EXISTS (SELECT FROM pg_namespace WHERE nspname IN ('ava_mcp_fixture_base','ava_mcp_preview')) AS present`);
    assert.equal(existing.rows[0].present, false, 'fixture objects already exist; refusing to overwrite');
    await admin.query('BEGIN');
    await admin.query(await readFile(new URL('./fixture.sql', import.meta.url), 'utf8'));
    await admin.query('COMMIT');
    created = true;
    const password = randomBytes(32).toString('hex');
    await admin.query(`ALTER ROLE ava_mcp_fixture_reader LOGIN PASSWORD '${password}'`);
    await admin.query(`INSERT INTO ava_mcp_fixture_base.jobs (id,status,step,retrieval_version,created_at,title,summary,action_items) VALUES
      ('private-1','done','done','hybrid-v1','2026-01-01 00:00:00.123456+00',repeat('t',201),repeat('s',1501),repeat('a',751)),
      ('private-2','done','done','legacy','2026-01-01 00:00:00.123455+00','secret','secret','secret'),
      ('private-3','deleting','done','hybrid-v1','2026-01-02+00','secret','secret','secret'),
      ('private-4','done','done','hybrid-v1','2026-01-03+00','secret','secret','secret'),
      ('private-5','error','unexpected private text','hybrid-v1','2026-01-04+00','secret','secret','secret')`);
    await admin.query(`INSERT INTO ava_mcp_fixture_base.shares (job_id, public_id, content_approved) VALUES
      ('private-1','00000000-0000-0000-0000-000000000001',true),
      ('private-2','00000000-0000-0000-0000-000000000002',true),
      ('private-3','00000000-0000-0000-0000-000000000003',true),
      ('private-4','00000000-0000-0000-0000-000000000004',false),
      ('private-5','00000000-0000-0000-0000-000000000005',true)`);
    await admin.query(`INSERT INTO ava_mcp_fixture_base.transcript_chunks VALUES ('private-1',0,repeat('x',501),0,10,'segment'),('private-1',1,'next',10,20,'segment'),('private-2',0,'legacy secret',NULL,NULL,'unknown')`);
    const readerUrl = new URL(url!);
    readerUrl.username = 'ava_mcp_fixture_reader';
    readerUrl.password = password;
    const reader = createReader(readerUrl.toString(), 'ava_mcp_preview');
    const rows = await reader.list(2);
    assert.deepEqual(rows.map((r) => r.job_id), ['00000000-0000-0000-0000-000000000005','00000000-0000-0000-0000-000000000004']);
    assert.equal((await reader.status('00000000-0000-0000-0000-000000000001'))?.created_at, '2026-01-01T00:00:00.123456Z');
    assert.equal(rows[0].step, null);
    assert.equal(rows[0].error_code, 'PROCESSING_FAILED');
    assert.deepEqual((await reader.list(2, {created_at: '2026-01-01T00:00:00.123456Z',job_id: '00000000-0000-0000-0000-000000000001'})).map((r) => r.job_id), ['00000000-0000-0000-0000-000000000002']);
    const summary = await reader.summary('00000000-0000-0000-0000-000000000001');
    assert.equal(summary?.summary?.length, 1500);
    assert.deepEqual(summary?.truncated_fields, ['title', 'summary', 'action_items']);
    const chunks = await reader.transcript('00000000-0000-0000-0000-000000000001', 1, -1);
    assert.equal(chunks?.chunks[0].text.length, 500);
    assert.equal((await reader.transcript('00000000-0000-0000-0000-000000000001', 1, 0))?.chunks[0].text, 'next');
    assert.equal((await reader.summary('00000000-0000-0000-0000-000000000002'))?.summary, null);
    assert.deepEqual((await reader.transcript('00000000-0000-0000-0000-000000000002', 5, -1))?.chunks, []);
    assert.equal(await reader.status('00000000-0000-0000-0000-000000000003'), null);
    assert.equal((await reader.status('00000000-0000-0000-0000-000000000004'))?.content_available, false);

    async function callTool(name: string, args: object) {
      const server = createServer(reader);
      const transport = new WebStandardStreamableHTTPServerTransport({ enableJsonResponse: true });
      await server.connect(transport);
      try {
        const response = await transport.handleRequest(new Request('http://127.0.0.1/mcp', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' },
          body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/call', params: { name, arguments: args } }),
        }));
        assert.equal(response.status, 200);
        const message = await response.json();
        assert.ok(isJSONRPCResultResponse(message) && isCallToolResult(message.result));
        const [content] = message.result.content;
        assert.ok(content?.type === 'text');
        assert.equal(message.result.isError, undefined, content.text);
        return JSON.parse(content.text);
      } finally {
        await server.close();
      }
    }

    const page = await callTool('list_videos', { limit: 1 });
    const listedAlias = page.items[0].job_id;
    assert.equal((await callTool('get_job_status', { job_id: listedAlias })).job_id, listedAlias);
    const nextPage = await callTool('list_videos', { limit: 1, cursor: page.next_cursor });
    assert.equal(nextPage.items[0].job_id, rows[1].job_id);

    const restricted = new Client({ connectionString: readerUrl.toString() });
    await restricted.connect();
    try {
      assert.equal((await restricted.query('SHOW statement_timeout')).rows[0].statement_timeout, '2s');
      await assert.rejects(restricted.query('SELECT * FROM ava_mcp_fixture_base.jobs'), { code: '42501' });
      const rights = await restricted.query("SELECT has_table_privilege(current_user, 'ava_mcp_preview.shared_jobs', 'INSERT') AS can_insert");
      assert.equal(rights.rows[0].can_insert, false);
      await assert.rejects(restricted.query('INSERT INTO ava_mcp_preview.shared_jobs DEFAULT VALUES'), (error: any) => ['42501', '55000'].includes(error.code));
    } finally { await restricted.end(); }
    await admin.query("DELETE FROM ava_mcp_fixture_base.shares WHERE job_id = 'private-1'");
    assert.equal(await reader.transcript('00000000-0000-0000-0000-000000000001', 1, 0), null);
    await admin.query("DELETE FROM ava_mcp_fixture_base.jobs WHERE id = 'private-2'");
    assert.equal(await reader.status('00000000-0000-0000-0000-000000000002'), null);
    assert.equal((await admin.query("SELECT 1 FROM ava_mcp_fixture_base.shares WHERE job_id = 'private-2'")).rowCount, 0);
  } finally {
    if (created) {
      await admin.query('DROP SCHEMA ava_mcp_preview CASCADE');
      await admin.query('DROP SCHEMA ava_mcp_fixture_base CASCADE');
      await admin.query('DROP ROLE ava_mcp_fixture_reader, ava_mcp_fixture_owner');
    } else {
      await admin.query('ROLLBACK');
    }
    await admin.end();
  }
});
