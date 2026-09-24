import { execFile } from 'node:child_process'
import { promisify } from 'node:util'
import path from 'node:path'
import { NextRequest, NextResponse } from 'next/server'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const execFileAsync = promisify(execFile)
const allowedKpis = new Set([
  'all', 'net_sales_revenue', 'orders', 'units_sold', 'traffic_total', 'conversion_rate',
])
const allowedRegions = new Set(['North', 'South', 'East', 'West'])
const allowedCategories = new Set(['Electronics', 'Apparel', 'Home'])

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams
  const kpi = params.get('kpi') ?? 'all'
  const date = params.get('date') ?? '2023-07-24'
  const region = params.get('region') ?? 'North'
  const category = params.get('category') ?? 'Electronics'

  if (!allowedKpis.has(kpi) || !allowedRegions.has(region) || !allowedCategories.has(category)
      || !/^202[34]-\d{2}-\d{2}$/.test(date)) {
    return NextResponse.json({ error: 'Unsupported KPI or demo filter.' }, { status: 400 })
  }

  const engineDir = path.resolve(process.cwd(), '..')
  const python = process.env.KPI_PYTHON ?? path.join(engineDir, '.venv', 'bin', 'python')
  try {
    const { stdout } = await execFileAsync(
      python,
      [path.join(engineDir, 'frontend_bridge.py'), '--kpi', kpi, '--date', date,
        '--region', region, '--category', category],
      {
        cwd: engineDir,
        timeout: 120_000,
        maxBuffer: 8 * 1024 * 1024,
        env: { ...process.env, GROQ_API_KEY: '' },
      },
    )
    return NextResponse.json(JSON.parse(stdout), {
      headers: { 'Cache-Control': 'no-store' },
    })
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Unknown engine error'
    return NextResponse.json({ error: `Engine request failed: ${message}` }, { status: 500 })
  }
}
