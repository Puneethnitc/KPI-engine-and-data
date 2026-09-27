'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import AppShell, { API_BASE, identityForPersona, State, useDemoContext } from '../../components/app-shell'
import type { SemanticContract } from '../../lib/semantic-contract'

export default function KpiContractsPage() {
  const { persona, region, category, ready } = useDemoContext()
  const [items, setItems] = useState<SemanticContract[]>([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!ready) return
    setLoading(true)
    const params = new URLSearchParams({
      user_id: identityForPersona(persona),
      region,
      category,
    })
    fetch(`${API_BASE}/api/kpis?${params}`)
      .then(async response => {
        if (response.status === 403) throw new Error('Contract metadata is not authorized for this scope.')
        if (response.status === 401) throw new Error('This identity is not authorized to inspect KPI contracts.')
        if (!response.ok) throw new Error('The KPI contract registry could not be loaded.')
        return response.json()
      })
      .then(payload => setItems(payload.items ?? []))
      .catch(requestError => setError(requestError.message))
      .finally(() => setLoading(false))
  }, [ready, persona, region, category])

  return <AppShell active="KPI Contracts" context="Governed KPI definitions">
    <div className="page-heading route-heading">
      <div><span className="eyebrow">Semantic registry</span><h1>KPI contracts</h1><p>Executable definitions and policy for {region} · {category}</p></div>
      <span className="evidence-pill">{items.length} authorized contracts</span>
    </div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {loading ? <State>Loading validated KPI contracts…</State> : !error && !items.length ? <State>No contracts are available for this identity and scope.</State> : <div className="contract-index">
      {items.map(contract => <Link className="card contract-index-row" href={`/kpis/${contract.identity.kpi_id}`} key={contract.identity.kpi_id}>
        <div><span className="eyebrow">{contract.identity.kpi_id} · v{contract.identity.version}</span><h2>{contract.identity.display_name}</h2><p>{contract.identity.definition}</p></div>
        <div className="contract-index-meta"><span>{contract.calculation.operator} · {contract.calculation.unit}</span><span>{contract.grain_and_scope.native_grain} · {contract.source.primary_source_id}</span><span>{contract.identity.owner}</span></div>
        <span className={`evidence-pill ${contract.governance.validation_status === 'VALID' ? 'good' : 'warning'}`}>{contract.governance.validation_status}</span>
      </Link>)}
    </div>}
  </AppShell>
}
