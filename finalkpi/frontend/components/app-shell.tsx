'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { BarChart3, Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createContext, useContext } from 'react'

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api/backend'
export const KPIS = [
  ['net_sales_revenue', 'Revenue'], ['orders', 'Orders'], ['units_sold', 'Units sold'],
  ['traffic_total', 'Traffic'], ['conversion_rate', 'Conversion rate'],
] as const
export const identityForPersona = (persona: string) => persona === 'CFO' ? 'demo-cfo' : 'demo-marketing'

type DemoContextValue = { persona: string; setPersona: (value: string) => void; region: string; setRegion: (value: string) => void; category: string; setCategory: (value: string) => void; date: string; setDate: (value: string) => void; theme: 'dark' | 'light'; setTheme: (value: 'dark' | 'light') => void }
const DemoContext = createContext<DemoContextValue | null>(null)

export function DemoProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [hydrated, setHydrated] = useState(false)
  const [persona, setPersona] = useState('marketing_manager')
  const [region, setRegion] = useState('North')
  const [category, setCategory] = useState('Electronics')
  const [date, setDate] = useState('2023-07-24')
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    let stored: Record<string, string> = {}
    try { stored = JSON.parse(sessionStorage.getItem('kpi-scope') || '{}') as Record<string, string> } catch { sessionStorage.removeItem('kpi-scope') }
    setPersona(['marketing_manager', 'CFO'].includes(params.get('persona') || '') ? params.get('persona')! : stored.persona === 'CFO' ? 'CFO' : 'marketing_manager')
    const validRegions = ['East', 'North', 'South', 'West']
    const validCategories = ['Apparel', 'Beauty', 'Electronics', 'Home']
    setRegion(validRegions.includes(params.get('region') || '') ? params.get('region')! : stored.region && validRegions.includes(stored.region) ? stored.region : 'North')
    setCategory(validCategories.includes(params.get('category') || '') ? params.get('category')! : stored.category && validCategories.includes(stored.category) ? stored.category : 'Electronics')
    setDate(/^\d{4}-\d{2}-\d{2}$/.test(params.get('date') || '') ? params.get('date')! : stored.date || '2023-07-24')
    setTheme(localStorage.getItem('kpi-theme') === 'light' ? 'light' : 'dark')
    setHydrated(true)
  }, [])
  useEffect(() => {
    sessionStorage.setItem('kpi-scope', JSON.stringify({ persona, region, category, date }))
    if (hydrated) {
      const params = new URLSearchParams(window.location.search)
      params.set('persona', persona); params.set('region', region); params.set('category', category); params.set('date', date)
      router.replace(`${pathname}?${params.toString()}`, { scroll: false })
    }
  }, [persona, region, category, date, hydrated, pathname, router])
  useEffect(() => localStorage.setItem('kpi-theme', theme), [theme])
  return <DemoContext.Provider value={{ persona, setPersona, region, setRegion, category, setCategory, date, setDate, theme, setTheme }}>{children}</DemoContext.Provider>
}

export function useDemoContext() {
  const value = useContext(DemoContext)
  if (!value) throw new Error('useDemoContext must be used within DemoProvider')
  return value
}

export default function AppShell({ children, active, context }: { children: React.ReactNode; active: string; context?: string }) {
  const demo = useDemoContext()
  const query = `?persona=${encodeURIComponent(demo.persona)}&region=${encodeURIComponent(demo.region)}&category=${encodeURIComponent(demo.category)}&date=${encodeURIComponent(demo.date)}`
  return <div className={`app-shell ${demo.theme}`}>
    <header className="topbar">
      <Link className="brand" href="/"><span className="brand-mark"><BarChart3 size={17} /></span><span>KPI <strong>Intelligence</strong></span></Link>
      <nav className="main-nav" aria-label="Primary navigation">
        {[['/', 'Overview'], ['/performance', 'Performance'], ['/campaigns', 'Campaigns'], ['/insights', 'Insights']].map(([href, label]) => <Link key={href} className={active === label ? 'active' : ''} href={`${href}${query}`}>{label}</Link>)}
      </nav>
      <div className="top-actions"><label className="persona-control">Demo persona<select value={demo.persona} onChange={event => demo.setPersona(event.target.value)}><option value="marketing_manager">Marketing Manager</option><option value="CFO">CFO</option></select></label><button className="theme-button" onClick={() => demo.setTheme(demo.theme === 'dark' ? 'light' : 'dark')} aria-label="Toggle theme">{demo.theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button><span className="avatar">{demo.persona === 'CFO' ? 'CF' : 'MM'}</span></div>
    </header>
    {context && <div className="route-context">Active scope: {context} · {demo.persona === 'CFO' ? 'CFO review' : 'Marketing Manager workspace'}</div>}
    <main className="workspace"><section className="dashboard-column">{children}</section></main>
  </div>
}

export function State({ children }: { children: React.ReactNode }) { return <div className="route-state">{children}</div> }
