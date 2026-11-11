import { createMcpHandler } from 'agents/mcp/server'
import { isOwner, readBody, validToken } from './auth.ts'
import { createReader } from './db.ts'
import { createServer } from './tools.ts'

export interface WorkerEnv {
  MCP_HOSTNAME?: string
  MCP_ENVIRONMENT?: string
  MCP_BEARER_TOKEN?: string
  HYPERDRIVE?: Pick<Hyperdrive, 'connectionString'>
  MCP_RATE_LIMIT?: RateLimit
}

function uncached(response: Response): Response {
  const headers = new Headers(response.headers)
  headers.set('Cache-Control', 'no-store')
  return new Response(response.body, { status: response.status, headers })
}

async function handle(request: Request, env: WorkerEnv): Promise<Response> {
  const url = new URL(request.url)
  if (url.pathname !== '/mcp') return new Response('Not found', { status: 404 })
  if (!env.MCP_HOSTNAME || !validToken(env.MCP_BEARER_TOKEN) ||
      (env.MCP_ENVIRONMENT !== 'production' && env.MCP_ENVIRONMENT !== 'preview')) {
    return new Response('Temporarily unavailable', { status: 503 })
  }
  const host = request.headers.get('host')
  const origin = request.headers.get('origin')
  if (url.host !== env.MCP_HOSTNAME || (host !== null && host !== env.MCP_HOSTNAME) ||
      (origin !== null && origin !== url.origin)) {
    return new Response('Forbidden', { status: 403 })
  }
  if (!isOwner(request.headers.get('authorization'), env.MCP_BEARER_TOKEN)) {
    return new Response('Unauthorized', { status: 401, headers: { 'WWW-Authenticate': 'Bearer' } })
  }
  if (request.method !== 'POST') {
    return new Response('Method not allowed', { status: 405, headers: { Allow: 'POST' } })
  }
  if (!env.MCP_RATE_LIMIT || !env.HYPERDRIVE?.connectionString) {
    return new Response('Temporarily unavailable', { status: 503 })
  }
  const decision = await env.MCP_RATE_LIMIT.limit({ key: 'owner' })
  if (!decision.success) {
    return new Response('Too many requests', { status: 429, headers: { 'Retry-After': '60' } })
  }

  const body = await readBody(request)
  if (body instanceof Response) return body
  const reader = createReader(
    env.HYPERDRIVE.connectionString,
    env.MCP_ENVIRONMENT === 'preview' ? 'ava_mcp_preview' : 'ava_mcp',
  )
  const handler = createMcpHandler(() => createServer(reader), {
    route: '/mcp',
    legacy: 'stateless',
    corsOptions: false,
    allowedHostnames: [url.hostname],
  })
  return handler.fetch(request, { parsedBody: body })
}

export default {
  async fetch(request: Request, env: WorkerEnv): Promise<Response> {
    try {
      return uncached(await handle(request, env))
    } catch {
      return uncached(new Response('Temporarily unavailable', { status: 503 }))
    }
  },
} satisfies ExportedHandler<WorkerEnv>
