import assert from 'node:assert/strict'
import test from 'node:test'
import {
  makeWorkerConfig, readReleaseSettings, smokeWorker, verifyDeployment, verifyDeploymentTarget,
} from '../scripts/release_worker.mjs'

const env = {
  CLOUDFLARE_API_TOKEN: 'synthetic-api-token',
  CLOUDFLARE_ACCOUNT_ID: 'a'.repeat(32),
  MCP_HOSTNAME: 'ai-video-assistant-mcp.demo-user.workers.dev',
  MCP_HYPERDRIVE_ID: 'b'.repeat(32),
  MCP_SMOKE_TOKEN: Buffer.alloc(32, 17).toString('base64url'),
  RELEASE_SHA: 'c'.repeat(40),
}
const versionId = 'e397bc09-609c-443f-9dc0-9becf78ab911'
const deployId = '6c2df210-3097-48ac-8a6a-e48c40f77921'
const tools = ['get_job_status', 'get_transcript', 'get_video_summary', 'list_videos']
  .map(name => ({ name, annotations: { readOnlyHint: true } }))

test('production deployment validates identifiers and uses the existing bindings', () => {
  const settings = readReleaseSettings(env)
  const config = makeWorkerConfig(settings)
  assert.equal(config.name, 'ai-video-assistant-mcp')
  assert.equal(config.account_id, env.CLOUDFLARE_ACCOUNT_ID)
  assert.deepEqual(config.hyperdrive, [{ binding: 'HYPERDRIVE', id: env.MCP_HYPERDRIVE_ID }])
  assert.deepEqual(config.vars, { MCP_HOSTNAME: env.MCP_HOSTNAME, MCP_ENVIRONMENT: 'production' })
  assert.equal(config.ratelimits[0].name, 'MCP_RATE_LIMIT')
  assert.equal(config.previews, undefined)
  assert.ok(!JSON.stringify(config).includes(env.MCP_SMOKE_TOKEN))
  for (const [name, value] of [
    ['MCP_HOSTNAME', 'https://ai-video-assistant-mcp.demo-user.workers.dev'],
    ['MCP_HOSTNAME', 'unrelated.demo-user.workers.dev'],
    ['MCP_HYPERDRIVE_ID', '00000000000000000000000000000001'],
    ['MCP_HYPERDRIVE_ID', '00000000000000000000000000000000'],
    ['CLOUDFLARE_ACCOUNT_ID', '00000000000000000000000000000000'],
    ['CLOUDFLARE_API_TOKEN', ''],
    ['MCP_SMOKE_TOKEN', 'token'],
    ['MCP_SMOKE_TOKEN', env.MCP_SMOKE_TOKEN + '\n'],
    ['RELEASE_SHA', 'HEAD'],
  ]) {
    assert.throws(() => readReleaseSettings({ ...env, [name]: value }), new RegExp(name))
  }
})

test('deployment status must match the newly deployed version at 100 percent', () => {
  const current = { id: deployId, versions: [{ version_id: versionId, percentage: 100 }] }
  assert.equal(verifyDeployment(current, versionId), deployId)
  assert.throws(() => verifyDeployment(current, deployId), /active deployment/)
  assert.throws(() => verifyDeployment({ ...current, id: deployId + '\n' }, versionId), /active deployment/)
  assert.throws(() => verifyDeployment({
    ...current, versions: [{ version_id: versionId, percentage: 50 }],
  }, versionId), /active deployment/)
})

test('the reported hostname must belong to the deployed Worker before sending a token', () => {
  const settings = readReleaseSettings(env)
  verifyDeploymentTarget([`https://${env.MCP_HOSTNAME}`], settings)
  assert.throws(() => verifyDeploymentTarget(['https://ai-video-assistant-mcp.other-account.workers.dev'], settings),
    /configured Worker hostname/)
})

test('hosted smoke authenticates and exercises only the bounded read', async () => {
  const calls = []
  await smokeWorker(readReleaseSettings(env), async (url, options) => {
    assert.equal(String(url), `https://${env.MCP_HOSTNAME}/mcp`)
    assert.equal(options.redirect, 'error')
    assert.equal(options.method, 'POST')
    const request = JSON.parse(options.body)
    calls.push(request.method)
    if (calls.length === 1) {
      assert.equal(options.headers.Authorization, undefined)
      return new Response(null, { status: 401 })
    }
    assert.equal(options.headers.Authorization, `Bearer ${env.MCP_SMOKE_TOKEN}`)
    let result
    if (request.method === 'initialize') result = { serverInfo: { name: 'ai-video-assistant' } }
    if (request.method === 'tools/list') result = { tools }
    if (request.method === 'tools/call') {
      assert.deepEqual(request.params, { name: 'list_videos', arguments: { limit: 1 } })
      result = { content: [{ type: 'text', text: '{"items":[],"next_cursor":null}' }] }
    }
    return new Response(`event: message\ndata: ${JSON.stringify({ jsonrpc: '2.0', id: request.id, result })}\n\n`, {
      headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-store' },
    })
  })
  assert.deepEqual(calls, ['initialize', 'initialize', 'tools/list', 'tools/call'])
})

test('hosted smoke stops on exposed or malformed endpoints without returning response content', async () => {
  const settings = readReleaseSettings(env)
  await assert.rejects(smokeWorker(settings, async () => new Response('private payload')), {
    message: 'MCP did not reject an unauthenticated request with HTTP 401',
  })
  let requests = 0
  await assert.rejects(smokeWorker(settings, async () => {
    if (++requests === 1) return new Response(null, { status: 401 })
    return new Response('private payload', {
      headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' },
    })
  }), { message: 'MCP initialize returned an invalid response' })
  assert.equal(requests, 2)
})
