import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'

test('performance metadata requests authorize both governed endpoints', () => {
  const source = fs.readFileSync(new URL('../app/performance/page.tsx', import.meta.url), 'utf8')
  assert.match(source, /const identity = identityForPersona\(persona\)/)
  assert.match(source, /api\/investigations\?persona=.*user_id=/)
  assert.match(source, /api\/kpis\?user_id=.*region=.*category=/)
  assert.match(source, /setError\(''\)/)
})
