'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { BarChart3, Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'
import { createContext, useContext } from 'react'

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? '/api/backend'
export const identityForPersona = (persona: string) => persona === 'CFO' ? 'demo-cfo' : 'demo-marketing'

type DemoContextValue = { ready: boolean; persona: string; setPersona: (value: string) => void; region: string; setRegion: (value: string) => void; category: string; setCategory: (value: string) => void; date: string; setDate: (value: string) => void; theme: 'dark' | 'light'; setTheme: (value: 'dark' | 'light') => void }
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
  const [allowed, setAllowed] = useState<{ personas: string[]; regions: string[]; categories: string[]; dates: string[] }>({ personas: [], regions: [], categories: [], dates: [] })
  useEffect(() => {
    let stored: Record<string, string> = {}
    try { stored = JSON.parse(sessionStorage.getItem('kpi-scope') || '{}') as Record<string, string> } catch { sessionStorage.removeItem('kpi-scope') }
    setTheme(localStorage.getItem('kpi-theme') === 'light' ? 'light' : 'dark')
    fetch(`${API_BASE}/api/filters`, { cache: 'no-store' }).then(response => response.ok ? response.json() : Promise.reject(new Error('Metadata unavailable'))).then(payload => {
      const values = payload.allowed_values ?? {}
      const allowedValues = { personas: payload.persona ?? [], regions: values.region ?? payload.regions ?? [], categories: values.category ?? payload.categories ?? [], dates: payload.dates ?? [] }
      setAllowed(allowedValues)
      const params = new URLSearchParams(window.location.search)
      const choose = (key: keyof typeof stored, valid: string[], fallback?: string) => {
        const fromUrl = params.get(key)
        if (fromUrl && valid.includes(fromUrl)) return fromUrl
        if (stored[key] && valid.includes(stored[key])) return stored[key]
        return fallback ?? valid[0] ?? ''
      }
      setPersona(choose('persona', allowedValues.personas, payload.default?.persona || 'marketing_manager'))
      setRegion(choose('region', allowedValues.regions, payload.default?.region))
      setCategory(choose('category', allowedValues.categories, payload.default?.category))
      setDate(choose('date', allowedValues.dates, payload.default?.date))
    }).catch(() => {
      const params = new URLSearchParams(window.location.search)
      setPersona(params.get('persona') === 'CFO' || stored.persona === 'CFO' ? 'CFO' : 'marketing_manager')
      setRegion(params.get('region') || stored.region || 'North')
      setCategory(params.get('category') || stored.category || 'Electronics')
      setDate(params.get('date') || stored.date || '2023-07-24')
    }).finally(() => setHydrated(true))
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
  useEffect(() => {
    const restoreUrlScope = () => {
      const params = new URLSearchParams(window.location.search)
      if (params.get('persona') && allowed.personas.includes(params.get('persona')!)) setPersona(params.get('persona')!)
      if (params.get('region') && allowed.regions.includes(params.get('region')!)) setRegion(params.get('region')!)
      if (params.get('category') && allowed.categories.includes(params.get('category')!)) setCategory(params.get('category')!)
      if (params.get('date') && allowed.dates.includes(params.get('date')!)) setDate(params.get('date')!)
    }
    window.addEventListener('popstate', restoreUrlScope)
    return () => window.removeEventListener('popstate', restoreUrlScope)
  }, [allowed])
  return <DemoContext.Provider value={{ ready: hydrated, persona, setPersona, region, setRegion, category, setCategory, date, setDate, theme, setTheme }}>{children}</DemoContext.Provider>
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
