import assert from 'node:assert/strict'
import { test } from 'node:test'
import { isOwner, readBody, validToken } from '../src/auth.ts'

const token = Buffer.alloc(32, 17).toString('base64url')

test('bearer tokens use the canonical 32-byte representation', () => {
  assert.equal(validToken(token), true)
  assert.equal(isOwner(`bearer ${token}`, token), true)
  assert.equal(isOwner(`Bearer ${'A'.repeat(43)}`, token), false)
  assert.equal(isOwner(`Bearer ${token}=`, token), false)
  assert.equal(validToken(token.slice(0, -1) + 'B'), false)
})

test('body cap applies to streams without Content-Length and batches are rejected', async () => {
  const headers = { 'content-type': 'application/json' }
  const streamInit: RequestInit & { duplex: 'half' } = {
    method: 'POST', headers, duplex: 'half',
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new Uint8Array(16 * 1024))
        controller.enqueue(new Uint8Array(1))
        controller.close()
      },
    }),
  }
  const streamed = new Request('http://127.0.0.1/mcp', streamInit)
  const oversized = await readBody(streamed)
  assert.ok(oversized instanceof Response)
  assert.equal(oversized.status, 413)
  const batch = await readBody(new Request('http://127.0.0.1/mcp', { method: 'POST', headers, body: '[]' }))
  assert.ok(batch instanceof Response)
  assert.equal(batch.status, 400)
})

const url = process.env.AVA_MCP_TEST_URL
const fixtureJob = process.env.AVA_MCP_TEST_JOB
const workerToken = process.env.AVA_MCP_TEST_TOKEN

test('Wrangler serves authenticated legacy and modern MCP, with bounded tools and throttling',
  { skip: !url || !workerToken }, async () => {
    const target = new URL(url!)
    assert.ok(target.protocol === 'http:' && target.hostname === '127.0.0.1' && target.pathname === '/mcp')
    const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }
    const auth = { ...headers, Authorization: `Bearer ${workerToken}` }
    const send = (body: string, extra = auth) => fetch(target, { method: 'POST', headers: extra, body, signal: AbortSignal.timeout(12_000) })
    const rpc = (method: string, params: object = {}, extra = auth) =>
      send(JSON.stringify({ jsonrpc: '2.0', id: 1, method, params }), extra)
    async function result(response: Response) {
      assert.equal(response.status, 200, await response.clone().text())
      assert.equal(response.headers.get('cache-control'), 'no-store')
      const body = await response.text()
      return JSON.parse(response.headers.get('content-type')?.startsWith('text/event-stream')
        ? body.split('\n').find(line => line.startsWith('data: '))!.slice(6)
        : body).result
    }

    assert.equal((await send('[]', { ...auth, Authorization: 'Bearer invalid' })).status, 401)
    assert.equal((await send('[]', { ...auth, Origin: 'https://invalid.example' } as typeof auth)).status, 403)
    assert.equal((await fetch(target, { headers: auth })).status, 405)
    assert.equal((await send('[]')).status, 400)
    assert.equal((await send(JSON.stringify({ value: 'a'.repeat(16 * 1024) }))).status, 413)
    assert.equal((await result(await rpc('initialize', {
      protocolVersion: '2025-11-25', capabilities: {}, clientInfo: { name: 'local-test', version: '1' },
    }))).serverInfo.name, 'ai-video-assistant')

    const modern = { ...auth, 'MCP-Protocol-Version': '2026-07-28', 'Mcp-Method': 'tools/list' }
    for (const requestHeaders of [auth, modern]) {
      const params = requestHeaders === modern ? { _meta: {
        'io.modelcontextprotocol/protocolVersion': '2026-07-28',
        'io.modelcontextprotocol/clientInfo': { name: 'local-test', version: '1' },
        'io.modelcontextprotocol/clientCapabilities': {},
      } } : {}
      const listed = await result(await rpc('tools/list', params, requestHeaders))
      assert.deepEqual(listed.tools.map((tool: { name: string }) => tool.name).sort(),
        ['get_job_status', 'get_transcript', 'get_video_summary', 'list_videos'])
      assert.ok(listed.tools.every((tool: { annotations?: { readOnlyHint?: boolean } }) => tool.annotations?.readOnlyHint))
    }
    const call = (name: string, args: object) => rpc('tools/call', { name, arguments: args })
    const invalid = await result(await call('list_videos', { private_key_name: 'private_value' }))
    assert.equal(invalid.isError, true)
    assert.equal(JSON.parse(invalid.content[0].text).error.code, 'INVALID_INPUT')
    assert.ok(!invalid.content[0].text.includes('private_key_name'))

    if (fixtureJob) {
      const data = async (name: string, args: object) => JSON.parse((await result(await call(name, args))).content[0].text)
      const page = await data('list_videos', { limit: 1 })
      assert.equal(page.items.length, 1)
      assert.ok(page.next_cursor)
      assert.equal((await data('list_videos', { limit: 1, cursor: page.next_cursor })).items.length, 1)
      assert.deepEqual(await data('get_job_status', { job_id: fixtureJob }),
        { job_id: fixtureJob, status: 'done', step: 'done', error: null })
      assert.equal((await data('get_video_summary', { job_id: fixtureJob })).job_id, fixtureJob)
      const transcript = await data('get_transcript', { job_id: fixtureJob, limit: 1 })
      assert.equal(transcript.chunks.length, 1)
      assert.equal(transcript.chunks[0].timing_precision, 'segment')
      assert.ok(transcript.next_cursor)
      const next = await data('get_transcript', { job_id: fixtureJob, cursor: transcript.next_cursor })
      assert.equal(next.chunks[0].ordinal, 1)
      assert.equal(next.chunks[0].timing_precision, 'unknown')
      assert.equal(next.chunks[0].start_ms, null)
      assert.equal(next.next_cursor, null)
      assert.equal((await data('get_transcript', { job_id: 'a0000000-0000-4000-8000-000000000000',
        cursor: transcript.next_cursor })).error.code, 'INVALID_INPUT')
      assert.equal((await data('get_transcript', { job_id: 'a0000000-0000-4000-8000-000000000000' })).error.code, 'NOT_FOUND')
    } else {
      const unavailable = await result(await call('list_videos', {}))
      assert.equal(unavailable.isError, true)
      assert.equal(JSON.parse(unavailable.content[0].text).error.code, 'TEMPORARY_UNAVAILABLE')
    }

    let limited: Response | undefined
    for (let i = 0; i <= 20; i++) {
      const response = await rpc('tools/list')
      await response.text()
      if (response.status === 429) { limited = response; break }
      assert.equal(response.status, 200)
    }
    assert.equal(limited?.headers.get('Retry-After'), '60')
  },
)
