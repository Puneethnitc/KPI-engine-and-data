# Application UI

`page.tsx` is a client-side mentor-demo dashboard. It fetches a diagnosis result, presents the five registered KPIs, lets the reviewer change the supplied date/region/category scope, and clearly separates observed movement, exact accounting, correlation candidates, observational status, and human review.

`globals.css` holds the dashboard theme and layout. `layout.tsx` supplies the shared Next.js document shell. The chat panel is a deterministic, result-bound explainer; it is not a live LLM.
