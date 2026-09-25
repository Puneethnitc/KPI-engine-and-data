import { NextRequest } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const BACKEND_URL = process.env.KPI_BACKEND_URL ?? 'http://127.0.0.1:8000'
const ALLOWED_ROOTS = new Set(['filters', 'kpis', 'diagnoses', 'chat', 'conversations', 'feedback'])

async function proxy(request: NextRequest) {
  const segments = request.nextUrl.pathname
    .replace(/^\/api\/backend\/?/, '')
    .split('/')
    .filter(Boolean)
  const path = segments[0] === 'api' ? segments.slice(1) : segments
  if (!path.length || !ALLOWED_ROOTS.has(path[0])) {
    return Response.json({ detail: 'Unsupported backend route.' }, { status: 404 })
  }

  const target = new URL(`/api/${path.map(encodeURIComponent).join('/')}`, BACKEND_URL)
  target.search = request.nextUrl.search
  const hasBody = !['GET', 'HEAD'].includes(request.method)

  try {
    const response = await fetch(target, {
      method: request.method,
      headers: { 'Content-Type': request.headers.get('content-type') ?? 'application/json' },
      body: hasBody ? await request.text() : undefined,
      cache: 'no-store',
    })
    return new Response(response.body, {
      status: response.status,
      headers: { 'Content-Type': response.headers.get('content-type') ?? 'application/json' },
    })
  } catch {
    return Response.json({ detail: 'The KPI backend is unavailable.' }, { status: 503 })
  }
}

export const GET = proxy
export const POST = proxy
