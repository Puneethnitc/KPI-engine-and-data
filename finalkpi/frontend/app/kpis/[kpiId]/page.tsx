'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import AppShell, { API_BASE, identityForPersona, State, useDemoContext } from '../../../components/app-shell'
import SemanticContractViewer, { ContractStateNotice } from '../../../components/semantic-contract-viewer'
import { contractRequestPath, contractRequestState, type ContractComparison, type SemanticContract } from '../../../lib/semantic-contract'

type RunContractResponse = {
  run_id: string
  kpi_id: string
  contract_snapshot: SemanticContract | null
  current_contract: SemanticContract | null
  comparison: ContractComparison
}

export default function KpiContractDetailPage({ params }: { params: Promise<{ kpiId: string }> }) {
  const searchParams = useSearchParams()
  const runId = searchParams.get('run_id')
  const { persona, region, category, ready } = useDemoContext()
  const [kpiId, setKpiId] = useState('')
  const [contract, setContract] = useState<SemanticContract | null>(null)
  const [runContract, setRunContract] = useState<RunContractResponse | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'unauthorized' | 'not-found' | 'invalid' | 'error'>('loading')
  const [message, setMessage] = useState('')

  useEffect(() => { params.then(value => setKpiId(value.kpiId)) }, [params])

  useEffect(() => {
    if (!ready || !kpiId) return
    setContract(null)
    setRunContract(null)
    setMessage('')
    setState('loading')
    const identity = identityForPersona(persona)
    const requestUrl = runId
      ? `${API_BASE}${contractRequestPath(kpiId, runId)}?user_id=${encodeURIComponent(identity)}`
      : `${API_BASE}${contractRequestPath(kpiId)}?user_id=${encodeURIComponent(identity)}&region=${encodeURIComponent(region)}&category=${encodeURIComponent(category)}`
    fetch(requestUrl).then(async response => {
      const requestState = contractRequestState(response.status)
      if (requestState !== 'ready') {
        const error = new Error(requestState === 'unauthorized'
          ? 'Contract metadata is not authorized for this identity or scope.'
          : requestState === 'not-found'
            ? 'The requested KPI contract or saved run was not found.'
            : requestState === 'invalid'
              ? 'The contract endpoint rejected an invalid contract request.'
              : 'The contract endpoint returned an error.') as Error & { status: number }
        error.status = response.status
        throw error
      }
      return response.json()
    }).then(payload => {
      if (runId) {
        const saved = payload as RunContractResponse
        setRunContract(saved)
        if (!saved.contract_snapshot) {
          setState('invalid')
          setMessage('Contract snapshot was not saved for this run.')
          return
        }
        if (saved.contract_snapshot.governance.validation_status !== 'VALID') {
          setState('invalid')
          setMessage('The saved contract snapshot is marked invalid.')
          return
        }
      } else {
        const current = payload as SemanticContract
        setContract(current)
        if (current.governance.validation_status !== 'VALID') {
          setState('invalid')
          setMessage('The current KPI contract failed validation.')
          return
        }
      }
      setState('ready')
    }).catch((requestError: Error & { status?: number }) => {
      setMessage(requestError.message)
      const requestState = requestError.status ? contractRequestState(requestError.status) : state
      if (requestState === 'unauthorized') setState('unauthorized')
      else if (requestState === 'not-found') setState('not-found')
      else if (requestState === 'invalid') setState('invalid')
      else setState('error')
    })
  }, [ready, kpiId, runId, persona, region, category])

  const viewed = runId ? runContract?.contract_snapshot : contract
  return <AppShell active="KPI Contracts" context={runId ? `Run ${runId} contract snapshot` : 'Current contract'}>
    <Link className="back-link" href={runId ? `/performance/${runId}` : '/kpis'}>Back to {runId ? 'investigation' : 'contracts'}</Link>
    {state !== 'ready' && <ContractStateNotice state={state} message={message || undefined} />}
    {state === 'ready' && viewed && <SemanticContractViewer
      snapshot={viewed}
      current={runContract?.current_contract}
      comparison={runContract?.comparison}
      persona={persona}
      historical={Boolean(runId)}
    />}
  </AppShell>
}
