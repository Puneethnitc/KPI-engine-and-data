import test from 'node:test'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'

const require = createRequire(import.meta.url)
const Module = require('node:module')
const ts = require('typescript')
for (const extension of ['.ts', '.tsx']) {
  Module._extensions[extension] = (module, filename) => {
    const source = require('node:fs').readFileSync(filename, 'utf8')
    module._compile(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true }, fileName: filename }).outputText, filename)
  }
}
const React = require('react')
const { renderToStaticMarkup } = require('react-dom/server')
const { default: ExecutiveSummary, summaryBadge } = require('../components/executive-summary.tsx')

const summary = {
  status: 'LLM',
  sentences: [{ text: 'Revenue rose ₹377.', facts: ['F2'] }],
  do_first: { text: 'Check stock.', facts: ['F5', 'F99'] },
  facts: [{ id: 'F2', text: 'Revenue changed +₹377.' }, { id: 'F5', text: 'Driver Stock availability.' }],
}

test('badge distinguishes AI from template', () => {
  assert.equal(summaryBadge('LLM'), 'Written by AI from verified facts')
  assert.equal(summaryBadge('TEMPLATE'), 'Template (AI unavailable)')
})

test('summary shows citation chips with the fact as hover text, skipping unknown ids', () => {
  const html = renderToStaticMarkup(React.createElement(ExecutiveSummary, { summary }))
  assert.match(html, /title="Revenue changed \+₹377\."[^>]*>F2</)
  assert.doesNotMatch(html, /F99/)
  assert.match(html, /What to do first/)
  assert.match(html, /Written by AI from verified facts/)
})

test('missing summary (older run) renders nothing', () => {
  assert.equal(renderToStaticMarkup(React.createElement(ExecutiveSummary, { summary: null })), '')
})
