'use client'

import { useState } from 'react'
import type { DriverAnalysis, ExcludedDriver, RankedDriver } from '../lib/driver-analysis'
import { attributionPercent, type ConfidenceProfile, type AttributionConfidenceDriver } from '../lib/confidence-profile'
import { driverRows, exclusionReason } from '../lib/driver-analysis-overview'
import { formatKpiValue } from '../lib/driver-waterfall'
import DriverWaterfall from './driver-waterfall'

export type CausalTest = {
  driver_id?: string
  verdict?: string
  reason?: string
  did_effect?: number | null
  method?: string
  controls_used?: { region?: string; category?: string }[]
}

function humanize(value?: string | null) {
  return value ? value.replaceAll('_', ' ').toLowerCase().replace(/(^|\s)\S/g, letter => letter.toUpperCase()) : 'Not assessed'
}

function driverMovement(driver: RankedDriver) {
  if (driver.driver_change == null || !Number.isFinite(driver.driver_change)) return 'Not available for this older run'
  const change = driver.driver_change
  const isShare = /share|ratio|rate|percent/i.test(driver.driver_unit ?? '')
  const amount = isShare ? `${(Math.abs(change) * 100).toFixed(0)}%` : `${Math.abs(change).toLocaleString('en-IN', { maximumFractionDigits: 2 })} ${driver.driver_unit ?? 'units'}`
  const strength = driver.driver_change_z == null ? '' : ` (${Math.abs(driver.driver_change_z) >= 3 ? 'strong' : Math.abs(driver.driver_change_z) >= 1.5 ? 'noticeable' : 'small'})`
  return `${change < 0 ? 'Fell' : change > 0 ? 'Rose' : 'Unchanged'} ${amount}${strength}`
}

function confidenceValue(driver: RankedDriver, record?: AttributionConfidenceDriver) {
  return record?.attribution_confidence ?? driver.attribution_confidence ?? null
}

function causalVerdict(value?: string) {
  return value === 'SUPPORTED_CONDITIONAL' ? 'SUPPORTED' : value ?? 'Not assessed'
}

export default function DriverAnalysisOverview({ analysis, profile, causalTest, expected, actual, isMaterial, unit, displayNames }: {
  analysis?: DriverAnalysis | null
  profile?: ConfidenceProfile | null
  causalTest?: CausalTest | null
  expected?: number | null
  actual?: number | null
  isMaterial?: boolean | null
  unit: string
  displayNames?: Record<string, string>
}) {
  const [infoOpen, setInfoOpen] = useState(false)
  if (!analysis) return <section className="card driver-overview"><span className="eyebrow">Driver analysis</span><h2>Analysis not available for this older run</h2><p>No saved driver snapshot can be shown.</p></section>
  const { rows, main } = driverRows(analysis, profile)
  const mainDriver = main?.driver
  const mainConfidence = mainDriver ? confidenceValue(mainDriver, main?.confidence) : null
  const verified = !!mainDriver && causalTest?.driver_id === mainDriver.driver_id && causalTest.verdict === 'SUPPORTED_CONDITIONAL'
  const docs = mainDriver?.corroboration?.supporting_documents ?? []
  const controls = causalTest?.controls_used?.length
  const causalPercent = verified && causalTest?.did_effect != null && Number.isFinite(causalTest.did_effect) && (causalTest.method ?? 'log_outcome').includes('log')
    ? Math.expm1(causalTest.did_effect) * 100 : null
  const question = profile?.attribution_status === 'AMBIGUOUS'
    ? 'Which of the similarly supported drivers should we verify first?'
    : profile?.attribution_status === 'NO_CONFIDENT_DRIVER'
      ? 'Which lever should we verify first?'
      : 'Review the driver evidence before naming a cause.'

  return <section className="card driver-overview" aria-label="Driver analysis">
    <div className="card-heading driver-overview-heading"><div><span className="eyebrow">Driver analysis</span><h2>What explains the movement?</h2></div><div className="driver-overview-actions"><span className={`evidence-pill ${verified ? 'good' : 'limited'}`}>{verified ? 'Verified cause' : 'Statistical, not verified'}</span><button type="button" className="movements-info-button" aria-label="Explain driver analysis terms" aria-expanded={infoOpen} onClick={() => setInfoOpen(value => !value)}>ⓘ</button></div></div>
    {infoOpen && <div className="driver-info-popover" role="note">
      <p><strong>Contribution</strong> estimates a driver’s portion of the KPI change; <strong>explained share</strong> compares it with the total change. Shares can exceed 100% when other drivers offset a movement or an unexplained remainder remains.</p>
      <p><strong>Lag</strong> is the delay between driver and KPI observations. <strong>Moved / z-score</strong> says how unusual the driver’s change was. The <strong>direction check</strong> compares the observed direction with the contract’s expectation.</p>
      <p><strong>Causal test:</strong> supported means an observational test supports the driver conditionally; rejected conflicts with it; inconclusive cannot decide; untestable lacks enough evidence. <strong>Attribution Confidence</strong> combines saved evidence for each driver; caps limit it when key checks, such as a verified test, are missing.</p>
    </div>}
    <div className={`driver-main-banner ${isMaterial !== false && mainDriver ? 'has-main' : ''}`}>
      {isMaterial === false ? <strong>This change is within the normal range. Drivers are shown for exploration only</strong> : mainDriver ? <><strong>Main cause: {mainDriver.display_name ?? displayNames?.[mainDriver.driver_id] ?? humanize(mainDriver.driver_id)}</strong><span>{mainConfidence == null ? 'Confidence not available' : `${attributionPercent(mainConfidence)}% ${main?.confidence?.label ?? mainDriver.label ?? humanize(main?.confidence?.band ?? mainDriver.band)}`}{verified ? ` · Verified by causal test${causalPercent == null ? '' : ` (${causalPercent < 0 ? '−' : '+'}${Math.abs(causalPercent).toFixed(0)}%${controls ? `, ${controls} comparison slices` : ''})`}` : ''}{docs.length ? ` · Supported by ${docs.join(', ')}` : ''}</span></> : <><strong>No confident cause</strong><span>{question}</span></>}
    </div>
    <div className="driver-overview-chart"><div className="driver-overview-subhead"><h3>Expected to Actual</h3><small>Saved statistical contributions; the causal test is shown separately</small></div><DriverWaterfall expected={expected} actual={actual} drivers={(analysis.ranked_drivers ?? []).map(driver => ({ label: driver.display_name ?? displayNames?.[driver.driver_id] ?? humanize(driver.driver_id), value: driver.contribution, offsetting: driver.offsetting }))} residual={analysis.residual} unit={unit} /></div>
    <div className="driver-overview-subhead"><h3>All drivers for this KPI</h3><small>{rows.length} candidates · includes excluded drivers</small></div>
    {rows.length ? <div className="driver-table-scroll"><table className="driver-table"><thead><tr><th>Driver</th><th>Moved?</th><th>Contribution</th><th>Direction</th><th>Causal test</th><th>Evidence</th><th>Confidence</th><th>Role</th></tr></thead><tbody>
      {rows.map(row => {
        const driver = row.driver
        const ranked: RankedDriver | null = row.kind === 'ranked' ? row.driver as RankedDriver : null
        const excluded: ExcludedDriver | null = row.kind === 'excluded' ? row.driver as ExcludedDriver : null
        const score = ranked ? confidenceValue(ranked, row.confidence) : row.confidence?.attribution_confidence
        const tested = causalTest?.driver_id === driver.driver_id
        const documents = ranked?.corroboration?.documents?.map(item => item.doc_id).filter(Boolean) ?? []
        const caps = row.confidence?.caps_applied ?? []
        const role = row.kind === 'excluded' ? 'Excluded' : isMaterial !== false && mainDriver?.driver_id === driver.driver_id ? 'Main cause' : ranked?.offsetting ? 'Offsetting' : 'Contributing'
        return <tr key={`${row.kind}-${driver.driver_id}`}>
          <td><strong>{ranked?.display_name ?? displayNames?.[driver.driver_id] ?? humanize(driver.driver_id)}</strong><small>{ranked?.controllability ? humanize(ranked.controllability) : 'Role not saved'}</small>{excluded && <small>{exclusionReason(excluded.reason_code)}</small>}{row.correlation != null && <details><summary>Legacy association (different method) ⓘ</summary><small>Lagged first differences; this can disagree with the attribution regression direction.</small><small>Legacy association: {row.correlation.toFixed(2)}</small></details>}</td>
          <td>{ranked ? <>{driverMovement(ranked)}<small>Lag: {ranked.lag_days ?? 'unknown'} days</small></> : 'Not assessed'}</td>
          <td>{ranked ? <>{formatKpiValue(ranked.contribution, unit, true)}<small>{ranked.explained_share == null ? 'Share unavailable' : `${(ranked.explained_share * 100).toFixed(0)}% share`}</small></> : '—'}</td>
          <td>{ranked?.direction_consistent === true ? '✓ Matches' : ranked?.direction_consistent === false ? '✗ Conflicts' : '—'}{ranked && <small>Expected {ranked.expected_direction ?? '—'} · observed {ranked.direction ?? '—'}</small>}</td>
          <td>{tested ? <><strong>{causalVerdict(causalTest.verdict)}</strong><small>{causalTest.reason ?? 'Reason not saved'}</small></> : 'Not tested'}</td>
          <td>{ranked?.corroboration ? <>{humanize(ranked.corroboration.status)}<small>{documents.length ? documents.join(', ') : 'No document IDs'}</small></> : 'Not available for this older run'}</td>
          <td>{score == null ? 'Not computed' : <><strong>{attributionPercent(score)}% {row.confidence?.label ?? ranked?.label ?? humanize(row.confidence?.band ?? ranked?.band)}</strong><div className="driver-confidence-track"><i style={{ width: `${attributionPercent(score)}%` }} /></div></>}{caps.length > 0 && <small>{caps.map(cap => `Capped at ${(cap.max * 100).toFixed(0)}%: ${cap.reason}`).join('; ')}</small>}{row.confidence?.evidence?.length ? <details><summary>Evidence breakdown</summary><ul>{row.confidence.evidence.map(item => <li key={item.id}>{item.name}: {item.weight_contribution >= 0 ? '+' : ''}{item.weight_contribution}{item.note ? ` · ${item.note}` : ''}</li>)}</ul></details> : null}</td>
          <td><span className={`driver-role ${role.toLowerCase().replaceAll(' ', '-')}`}>{role}</span></td>
        </tr>
      })}
    </tbody></table></div> : <p className="driver-waterfall-empty">No candidate driver evidence was saved for this run.</p>}
  </section>
}
