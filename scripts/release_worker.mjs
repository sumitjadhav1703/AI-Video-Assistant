import { spawnSync } from 'node:child_process'
import { appendFileSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const workerDir = fileURLToPath(new URL('../mcp-server/', import.meta.url))
const workerName = 'ai-video-assistant-mcp'
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/
const resourceId = /^(?!0{31}[01]$)[a-f0-9]{32}$/
const hostname = /^ai-video-assistant-mcp\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.workers\.dev$/
const tools = ['get_job_status', 'get_transcript', 'get_video_summary', 'list_videos']

export function readReleaseSettings(env) {
  const required = (name, pattern) => {
    const value = env[name]
    if (typeof value !== 'string' || !pattern.test(value)) throw new Error(`Invalid or missing ${name}`)
    return value
  }
  return {
    apiToken: required('CLOUDFLARE_API_TOKEN', /^[A-Za-z0-9_-]+$/),
    accountId: required('CLOUDFLARE_ACCOUNT_ID', resourceId),
    hostname: required('MCP_HOSTNAME', hostname),
    hyperdriveId: required('MCP_HYPERDRIVE_ID', resourceId),
    smokeToken: required('MCP_SMOKE_TOKEN', /^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/),
    sha: required('RELEASE_SHA', /^[a-f0-9]{40}$/),
  }
}

export function makeWorkerConfig(settings) {
  const config = JSON.parse(readFileSync(join(workerDir, 'wrangler.jsonc'), 'utf8'))
  if (config.name !== workerName || !config.workers_dev || config.routes || config.route ||
      config.hyperdrive?.length !== 1 || config.hyperdrive[0].binding !== 'HYPERDRIVE') {
    throw new Error('Unexpected production Worker configuration')
  }
  delete config.$schema
  delete config.previews
  return {
    ...config,
    main: resolve(workerDir, config.main),
    account_id: settings.accountId,
    vars: { ...config.vars, MCP_HOSTNAME: settings.hostname, MCP_ENVIRONMENT: 'production' },
    hyperdrive: [{ binding: 'HYPERDRIVE', id: settings.hyperdriveId }],
  }
}

export function verifyDeployment(deployment, versionId) {
  if (!uuid.test(deployment?.id ?? '') || deployment.versions?.length !== 1 ||
      deployment.versions[0].version_id !== versionId || deployment.versions[0].percentage !== 100) {
    throw new Error('Cloudflare active deployment does not match the uploaded version')
  }
  return deployment.id
}

export function verifyDeploymentTarget(targets, settings) {
  if (!Array.isArray(targets) || !targets.includes(`https://${settings.hostname}`)) {
    throw new Error('Wrangler did not report the configured Worker hostname')
  }
}

export async function smokeWorker(settings, request = fetch) {
  const url = new URL('/mcp', `https://${settings.hostname}`)
  const initialize = {
    protocolVersion: '2025-11-25',
    capabilities: {},
    clientInfo: { name: 'sample-release', version: '1.0.0' },
  }
  let nextId = 0
  const rpc = async (method, params, authenticate = true) => {
    const id = ++nextId
    const headers = { 'Content-Type': 'application/json', Accept: 'application/json, text/event-stream' }
    if (authenticate) headers.Authorization = `Bearer ${settings.smokeToken}`
    try {
      const response = await request(url, {
        method: 'POST',
        redirect: 'error',
        headers,
        body: JSON.stringify({ jsonrpc: '2.0', id, method, params }),
        signal: AbortSignal.timeout(15_000),
      })
      if (!authenticate) {
        await response.body?.cancel()
        return response.status
      }
      if (response.status !== 200 || response.headers.get('cache-control') !== 'no-store') {
        await response.body?.cancel()
        return null
      }
      const contentType = response.headers.get('content-type')?.split(';', 1)[0]
      if (contentType !== 'application/json' && contentType !== 'text/event-stream') {
        await response.body?.cancel()
        return null
      }
      const body = await response.text()
      const message = JSON.parse(contentType === 'text/event-stream'
        ? body.split(/\r?\n/).find(line => line.startsWith('data: '))?.slice(6)
        : body)
      return message.jsonrpc === '2.0' && message.id === id && !message.error ? message.result : null
    } catch {
      // HTTP, stream, and parsing errors may include private response content.
      return null
    }
  }
  if (await rpc('initialize', initialize, false) !== 401) {
    throw new Error('MCP did not reject an unauthenticated request with HTTP 401')
  }
  if ((await rpc('initialize', initialize))?.serverInfo?.name !== 'ai-video-assistant') {
    throw new Error('MCP initialize returned an invalid response')
  }
  const listed = (await rpc('tools/list', {}))?.tools
  if (!Array.isArray(listed) || listed.length !== tools.length ||
      !tools.every(name => listed.some(tool => tool?.name === name && tool.annotations?.readOnlyHint === true))) {
    throw new Error('MCP tools/list did not return the expected read-only tools')
  }
  const read = await rpc('tools/call', { name: 'list_videos', arguments: { limit: 1 } })
  let page
  if (!read?.isError && read?.content?.[0]?.type === 'text') {
    try { page = JSON.parse(read.content[0].text) } catch { /* Keep returned content private. */ }
  }
  if (!Array.isArray(page?.items) || page.items.length > 1 ||
      (page.next_cursor !== null && typeof page.next_cursor !== 'string')) {
    throw new Error('MCP list_videos failed its bounded read')
  }
}

function deploy(settings, config) {
  const scratch = mkdtempSync(join(tmpdir(), 'ava-worker-release-'))
  try {
    const configPath = join(scratch, 'wrangler.json')
    const outputPath = join(scratch, 'output.jsonl')
    writeFileSync(configPath, JSON.stringify(config), { mode: 0o600 })
    const runWrangler = (args) => {
      const result = spawnSync(process.execPath, [
        join(workerDir, 'node_modules/wrangler/bin/wrangler.js'), '--config', configPath, ...args,
      ], {
        cwd: workerDir,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'pipe'],
        timeout: 120_000,
        env: {
          PATH: process.env.PATH, HOME: process.env.HOME, CI: 'true',
          CLOUDFLARE_API_TOKEN: settings.apiToken, CLOUDFLARE_ACCOUNT_ID: settings.accountId,
          CLOUDFLARE_LOAD_DEV_VARS_FROM_DOT_ENV: 'false',
          WRANGLER_SEND_METRICS: 'false', WRANGLER_LOG_PATH: join(scratch, 'wrangler.log'),
          WRANGLER_OUTPUT_FILE_PATH: outputPath,
        },
      })
      if (result.status !== 0) throw new Error(`Wrangler ${args.join(' ')} failed`)
      return result.stdout
    }
    runWrangler(['deploy'])
    let record
    try {
      const records = readFileSync(outputPath, 'utf8').trim().split('\n').map(line => JSON.parse(line))
      record = records.findLast(event => event.type === 'deploy' && event.worker_name === workerName)
    } catch {
      throw new Error('Wrangler did not produce readable deployment output')
    }
    const versionId = record?.version_id
    if (!uuid.test(versionId ?? '')) throw new Error('Wrangler did not report the uploaded Worker version')
    report(`### Cloudflare Worker\n\nCommit \`${settings.sha}\`, uploaded version \`${versionId}\`.\n`)
    const status = runWrangler(['deployments', 'status', '--json'])
    let deployment
    try { deployment = JSON.parse(status) } catch {
      throw new Error('Wrangler did not produce readable deployment status')
    }
    const deploymentId = verifyDeployment(deployment, versionId)
    report(`Deployment \`${deploymentId}\` is serving version \`${versionId}\` at 100%. Smoke check pending.\n`)
    verifyDeploymentTarget(record.targets, settings)
  } finally {
    rmSync(scratch, { recursive: true, force: true })
  }
}

function report(message) {
  console.log(message)
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, `${message}\n`)
}

async function main() {
  const settings = readReleaseSettings(process.env)
  const config = makeWorkerConfig(settings)
  if (process.argv.length === 3 && process.argv[2] === '--check-config') {
    console.log('Cloudflare Worker release settings validated')
    return
  }
  if (process.argv.length !== 2) throw new Error('Usage: node scripts/release_worker.mjs [--check-config]')
  deploy(settings, config)
  await smokeWorker(settings)
  report('Cloudflare MCP authentication, tools and bounded read verified.\n')
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    await main()
  } catch (error) {
    const message = error instanceof Error && /^(Invalid or missing |Unexpected production |Usage: |Wrangler |Cloudflare active |MCP )/.test(error.message)
      ? error.message
      : 'Cloudflare Worker release could not finish'
    console.error(message)
    process.exitCode = 1
  }
}
