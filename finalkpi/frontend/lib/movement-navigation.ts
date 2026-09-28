export type MovementTarget = {
  kpi_id: string
  region: string | null
  category: string | null
  target_date?: string | null
}

export function movementScopeOptions(values: string[], dimension: 'region' | 'category', persona: string): string[] {
  const allAllowed = dimension === 'region'
    ? persona === 'CFO' || persona === 'marketing_manager'
    : persona === 'CFO' || persona === 'marketing_manager' || persona === 'regional_manager_north'
  return allAllowed && !values.includes('ALL') ? ['ALL', ...values] : values
}

export function movementSelection(
  row: MovementTarget,
  currentDate: string,
  options: { regions: string[]; categories: string[]; dates: string[] },
  persona: string,
) {
  const region = row.region ?? 'ALL'
  const category = row.category ?? 'ALL'
  const date = row.target_date ?? currentDate
  if (!movementScopeOptions(options.regions, 'region', persona).includes(region)
    || !movementScopeOptions(options.categories, 'category', persona).includes(category)
    || !options.dates.includes(date)) return null
  return { scenarioId: '', region, category, date, kpiId: row.kpi_id }
}
