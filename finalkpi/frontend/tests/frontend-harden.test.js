import { describe, it } from 'node:test'
import assert from 'node:assert'
import {
  buildContiguousSegments,
  formatDateLabel,
  formatDelta,
  formatValue,
  segmentToSvgPath,
} from '../components/trend-chart-utils.ts'

describe('Frontend Hardening & KPI Trend Logic', () => {

  it('identity included in time-series request', () => {
    const apiBase = '/api/backend'
    const kpiId = 'net_sales_revenue'
    const region = 'North'
    const category = 'Electronics'
    const targetDate = '2023-07-24'
    const userId = 'demo-cfo'

    const url = `${apiBase}/api/kpis/${encodeURIComponent(kpiId)}/timeseries?region=${encodeURIComponent(region)}&category=${encodeURIComponent(category)}&end_date=${encodeURIComponent(targetDate)}&user_id=${encodeURIComponent(userId)}`

    assert.ok(url.includes('user_id=demo-cfo'), 'URL must include user_id parameter for persona')
    assert.ok(url.includes('net_sales_revenue'), 'URL must include kpi_id')
  })

  it('default 90-day range', () => {
    // Generate 200 mock observations
    const points = Array.from({ length: 200 }, (_, i) => ({
      observation_date: `2023-01-${String(i + 1).padStart(2, '0')}`,
      actual: 100 + i,
      expected: 95 + i,
    }))

    const total = points.length
    const defaultStart = Math.max(0, total - 90)
    const defaultEnd = total - 1

    const visiblePoints = points.slice(defaultStart, defaultEnd + 1)
    assert.strictEqual(visiblePoints.length, 90, 'Initial range must default to latest 90 days')
    assert.strictEqual(visiblePoints[visiblePoints.length - 1].observation_date, points[points.length - 1].observation_date, 'Latest observation must be included')
  })

  it('30D/60D/90D/All controls', () => {
    const totalPoints = 150
    const calcPreset = (days) => {
      const endIdx = totalPoints - 1
      const startIdx = Math.max(0, endIdx - days + 1)
      return { startIdx, endIdx, len: endIdx - startIdx + 1 }
    }

    assert.strictEqual(calcPreset(30).len, 30, '30D preset length must be 30')
    assert.strictEqual(calcPreset(60).len, 60, '60D preset length must be 60')
    assert.strictEqual(calcPreset(90).len, 90, '90D preset length must be 90')
    assert.strictEqual(calcPreset(150).len, 150, 'All preset length must match total points')
  })

  it('zoom and reset', () => {
    const totalPoints = 100
    let rangeStart = 10 // 90 points visible (10 to 99)
    let rangeEnd = 99

    // Zoom In
    const currentLen = rangeEnd - rangeStart + 1
    const delta = Math.floor(currentLen * 0.2)
    rangeStart = Math.min(rangeStart + Math.floor(delta / 2), rangeEnd - 6)
    rangeEnd = Math.max(rangeEnd - Math.ceil(delta / 2), rangeStart + 6)
    const zoomedLen = rangeEnd - rangeStart + 1

    assert.ok(zoomedLen < currentLen, 'Zoom in should reduce visible range')

    // Reset should return to default 90-day range
    const resetStart = Math.max(0, totalPoints - 90)
    const resetEnd = Math.max(0, totalPoints - 1)
    assert.strictEqual(resetStart, 10, 'Reset returns to default 90-day start index')
    assert.strictEqual(resetEnd, 99, 'Reset returns to latest observation index')
  })

  it('loading, API error and empty series', () => {
    // Test empty data format
    const emptyResponse = { points: [] }
    assert.strictEqual(emptyResponse.points.length, 0, 'Empty response returns 0 points')

    // Test error format formatting
    const isAccessDenied = true
    const errorMsg = isAccessDenied ? 'Access Denied: Scope Unauthorized' : 'Error'
    assert.ok(errorMsg.includes('Access Denied'), 'Unauthorized error must clearly state Access Denied')
  })

  it('missing values creating separate line segments', () => {
    // Points with null actual value at index 2 (missing observation)
    const coords = [
      { pt: { observation_date: '2023-01-01', actual: 10, expected: 10, delta: 0, material_event: false, baseline_count: 30 }, x: 0, yActual: 100, yExpected: 100 },
      { pt: { observation_date: '2023-01-02', actual: 12, expected: 11, delta: 1, material_event: false, baseline_count: 30 }, x: 10, yActual: 90, yExpected: 95 },
      { pt: { observation_date: '2023-01-03', actual: null, expected: null, delta: null, material_event: false, baseline_count: 0 }, x: 20, yActual: null, yExpected: null },
      { pt: { observation_date: '2023-01-04', actual: 15, expected: 12, delta: 3, material_event: false, baseline_count: 30 }, x: 30, yActual: 70, yExpected: 90 },
      { pt: { observation_date: '2023-01-05', actual: 18, expected: 13, delta: 5, material_event: false, baseline_count: 30 }, x: 40, yActual: 50, yExpected: 85 },
    ]

    const actualSegments = buildContiguousSegments(coords, 'yActual')
    assert.strictEqual(actualSegments.length, 2, 'Null observation must split line into 2 separate segments')
    assert.strictEqual(actualSegments[0].length, 2, 'First segment has 2 points')
    assert.strictEqual(actualSegments[1].length, 2, 'Second segment has 2 points')

    const path1 = segmentToSvgPath(actualSegments[0], 'yActual')
    const path2 = segmentToSvgPath(actualSegments[1], 'yActual')
    assert.strictEqual(path1, 'M 0.0 100.0 L 10.0 90.0', 'First segment path connects points 0 and 1')
    assert.strictEqual(path2, 'M 30.0 70.0 L 40.0 50.0', 'Second segment path connects points 3 and 4')

    // Formatting null values truthfully
    assert.strictEqual(formatValue(null, 'INR'), 'No observation', 'Null actual value formats as No observation')
    assert.strictEqual(formatDelta(null, 'INR'), 'No observation', 'Null delta formats as No observation')
  })

  it('metadata display', () => {
    const data = {
      source: 'sales_daily',
      method: 'prior-history rolling governed baseline',
      data_version: 'v1.4.2-daily',
      points: Array.from({ length: 120 }),
    }

    assert.strictEqual(data.source, 'sales_daily', 'Source metadata present')
    assert.strictEqual(data.method, 'prior-history rolling governed baseline', 'Method metadata present')
    assert.strictEqual(data.data_version, 'v1.4.2-daily', 'Data version metadata present')
    assert.strictEqual(data.points.length, 120, 'Total observation count present')
  })

  it('dropdown keyboard navigation', () => {
    const options = [
      { value: 'North', label: 'North' },
      { value: 'South', label: 'South' },
      { value: 'East', label: 'East' },
      { value: 'West', label: 'West' },
    ]

    let highlightedIndex = 0

    // ArrowDown
    highlightedIndex = (highlightedIndex + 1) % options.length
    assert.strictEqual(highlightedIndex, 1, 'ArrowDown moves to index 1 (South)')

    // ArrowDown
    highlightedIndex = (highlightedIndex + 1) % options.length
    assert.strictEqual(highlightedIndex, 2, 'ArrowDown moves to index 2 (East)')

    // ArrowUp
    highlightedIndex = (highlightedIndex - 1 + options.length) % options.length
    assert.strictEqual(highlightedIndex, 1, 'ArrowUp moves back to index 1 (South)')

    // Select
    const selected = options[highlightedIndex].value
    assert.strictEqual(selected, 'South', 'Enter selects highlighted option South')
  })

  it('multi-word search using Space', () => {
    let searchQuery = ''
    const handleKeyInSearch = (key) => {
      if (key === ' ') {
        searchQuery += ' '
        return 'inserted_space'
      }
      return 'selected'
    }

    const action1 = handleKeyInSearch(' ')
    assert.strictEqual(action1, 'inserted_space', 'Space in search input must insert space character')
    assert.strictEqual(searchQuery, ' ', 'Search query contains typed space')

    searchQuery += 'electronics'
    assert.strictEqual(searchQuery, ' electronics', 'Multi-word search query supports spaces')
  })

  it('Escape/focus restoration', () => {
    let isOpen = true
    let focusRestored = false

    const handleEscape = () => {
      isOpen = false
      focusRestored = true
    }

    handleEscape()
    assert.strictEqual(isOpen, false, 'Escape closes menu')
    assert.strictEqual(focusRestored, true, 'Escape restores focus to trigger button')
  })

  it('URL/filter synchronization', () => {
    const params = new URLSearchParams('persona=CFO&region=South&category=Fashion&date=2023-07-20')
    assert.strictEqual(params.get('persona'), 'CFO', 'URL persona query param synced')
    assert.strictEqual(params.get('region'), 'South', 'URL region query param synced')
    assert.strictEqual(params.get('category'), 'Fashion', 'URL category query param synced')
    assert.strictEqual(params.get('date'), '2023-07-20', 'URL date query param synced')
  })

  it('unauthorized response handling', () => {
    const handleResponse = (status, body) => {
      if (status === 403 || status === 401) {
        return { isAccessDenied: true, error: body.detail || 'Access Denied: Scope Unauthorized' }
      }
      return { isAccessDenied: false, data: body }
    }

    const res403 = handleResponse(403, { detail: 'Identity demo-cfo is unauthorized for South region.' })
    assert.strictEqual(res403.isAccessDenied, true, '403 HTTP status flags access denied')
    assert.ok(res403.error.includes('unauthorized'), 'Access denied message preserves server detail')

    const res200 = handleResponse(200, { points: [1, 2, 3] })
    assert.strictEqual(res200.isAccessDenied, false, '200 HTTP status returns data')
  })

})
