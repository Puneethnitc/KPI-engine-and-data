export function sourceStatus(status: string | null | undefined, sourceId: string) {
  switch (status) {
    case 'FULL': return { label: 'FULL', tone: 'full', meaning: 'Data covers the selected period.' }
    case 'PARTIAL': return { label: 'PARTIAL', tone: 'partial', meaning: sourceId === 'marketing_weekly' ? "This week's report is not published yet." : sourceId === 'finance_monthly' ? 'The month has not closed yet.' : 'Some dates in the selected period are not covered yet.' }
    case 'EMPTY': return { label: 'EMPTY', tone: 'empty', meaning: 'No rows for this region, category or period.' }
    case 'RESTRICTED': return { label: 'RESTRICTED', tone: 'restricted', meaning: 'RESTRICTED: used in the analysis, hidden for your role.' }
    default: return { label: 'NOT_LOADED', tone: 'empty', meaning: 'Not needed for this KPI, so it was not read.' }
  }
}

export function reconciliationStatus(status: string | null | undefined) {
  switch (status) {
    case 'AGREED': return { label: 'AGREED', tone: 'full', meaning: 'Independent sources agree within tolerance.' }
    case 'PENDING_CLOSE': return { label: 'PENDING_CLOSE', tone: 'partial', meaning: 'Finance has not closed this period yet.' }
    case 'DRIFT': return { label: 'DRIFT', tone: 'partial', meaning: 'The sources differ beyond the normal tolerance.' }
    case 'CONTRADICTED': return { label: 'CONTRADICTED', tone: 'contradicted', meaning: 'The sources disagree materially; review before acting.' }
    default: return { label: status ?? 'NOT_APPLICABLE', tone: 'empty', meaning: 'No independent comparison is available for this period.' }
  }
}

export function reconciliationMode(mode: string | null | undefined) {
  if (!mode) return null
  if (mode === 'closed_month' || mode === 'closed_period') return 'Closed month'
  if (mode === 'month_to_date' || mode === 'month_to_date_snapshot') return 'Month-to-date snapshot'
  return mode.replaceAll('_', ' ')
}
