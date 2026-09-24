# KPI investigation workspace — Figma brief

Status: design brief; no Figma file or frontend implementation yet.

## Goal

Create an analyst-familiar, evidence-first desktop dashboard for an eight-minute
jury pitch. The memorable flow is: spot a material revenue movement, inspect
source quality, separate accounting from hypotheses, see whether a predeclared
causal check is conclusive, and leave with a human-review next step.

Use the `finalkpi` engine as the source of analytical truth. Sample numbers in
mockups must be marked illustrative until copied from an actual engine response.
Never depict confidence diagnostics as a probability of causation.

## Screens to design

1. **Overview / investigation queue (1440px desktop).** Persistent sidebar
   navigation; top bar with date, region, category, and as-of context; five KPI
   cards for revenue, orders, units, traffic, and conversion rate; a trend
   preview; sortable investigation table with materiality, source status,
   detector agreement, and freshness. Use text-plus-color status labels.
2. **Investigation detail (primary demo screen).** Breadcrumb back to queue;
   KPI title and observed movement; actual-versus-baseline time series with
   event markers; source-reconciliation banner; exact accounting bridge where
   applicable; separate **Correlational candidates** section showing lag and
   paired-observation count; observational-verification section with verdict,
   DiD estimate/interval and failed assumptions; narrative claims with
   evidence-path drillthrough; next-check or approval-only decision card.
3. **Evidence / review drawer.** Selected claim, its evidence paths and source
   availability, explicit limitations, then a before/after correction form.
   Submission is marked `PENDING_REVIEW`; it does not rewrite the analysis.

## Important states

- `CONTRADICTED` stops diagnosis; do not show a confident cause below it.
- `NOT_RECONCILED`, `SEASONAL_REVIEW`, `INSUFFICIENT_HISTORY`, and
  `INCONCLUSIVE` are visible first-class states, not empty cards.
- Accounting effects are labelled **What changed**; driver ranking is labelled
  **Correlational hypotheses**; DiD is labelled **Observational check**.
- `SUPPORTED_CONDITIONAL` still says observational support, not proof.
- Not every KPI has an accounting bridge or comparable finance source; use
  `Not applicable` with a short explanation rather than a blank chart.

## Engine-to-UI mapping

| UI element | Engine output |
| --- | --- |
| KPI status | `verdict`, `movement_assessment` |
| Actual change and materiality | `movement_assessment.delta`, `is_material`, statistical/business flags |
| Source banner | `reconciliation_verdict`, `source_coverage` |
| Accounting bridge | `decomposition_status`, `decomposition` |
| Hypothesis rows | `correlational_candidates`, `driver_exclusions` |
| Observational result | `causal_verdict`, `causal_verification` |
| Evidence-linked text | `narrative`, `narrative_claims`, `grounding_passed` |
| Proposed next check/action | `decision_cards` |
| Correction | `submit_feedback` before/after fields; API still required |

Time-series data, list/filter endpoints, authenticated identity, persisted run
lookup, and review-state retrieval are **not** supplied by the current
`finalkpi` public output. The design may show those interactions, but backend
contracts must be added before calling them working features.

## Visual direction

Use a restrained enterprise palette: ink/navy text, pale neutral background,
white surfaces, teal for navigation and primary actions, amber for review,
red for contradiction, and muted blue for informational evidence. Dense but
legible tables, clear numeric alignment, unobtrusive chart gridlines, and
consistent status badges should feel familiar to Power BI/Grafana users.
Avoid a generic grid of oversized cards or a chat-first layout.

## Eight-minute demo path

Open overview → select the revenue alert → show source status and accounting
bridge → distinguish candidates from verified findings → open one evidence
claim → show the inconclusive result and a safe next check. Show the other
four KPI cards only briefly. Keep a screenshot/recorded fallback for the live
demo.
