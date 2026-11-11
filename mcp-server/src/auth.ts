import { timingSafeEqual } from 'node:crypto'

const TOKEN = /^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$/
const MAX_BODY = 16 * 1024

export function validToken(value: unknown): value is string {
  return typeof value === 'string' && TOKEN.test(value)
}

export function isOwner(header: string | null, secret: string): boolean {
  if (header?.slice(0, 7).toLowerCase() !== 'bearer ') return false
  const token = header.slice(7)
  return validToken(token) && timingSafeEqual(Buffer.from(token), Buffer.from(secret))
}

export async function readBody(request: Request): Promise<unknown | Response> {
  const type = request.headers.get('content-type')?.split(';', 1)[0].trim().toLowerCase()
  if (type !== 'application/json') return new Response('Expected application/json', { status: 415 })
  if (Number(request.headers.get('content-length')) > MAX_BODY) {
    return new Response('Request too large', { status: 413 })
  }

  const stream = request.body?.getReader()
  if (!stream) return new Response('Expected a JSON request', { status: 400 })
  const bytes = new Uint8Array(MAX_BODY)
  let size = 0
  try {
    while (true) {
      const { done, value } = await stream.read()
      if (done) break
      if (size + value.length > MAX_BODY) {
        void stream.cancel().catch(() => {})
        return new Response('Request too large', { status: 413 })
      }
      bytes.set(value, size)
      size += value.length
    }
    const body: unknown = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes.subarray(0, size)))
    if (body !== null && typeof body === 'object' && !Array.isArray(body)) return body
  } catch {
    // Parse and stream errors can include private payload text.
  } finally {
    stream.releaseLock()
  }
  return new Response('Expected one JSON object', { status: 400 })
}
