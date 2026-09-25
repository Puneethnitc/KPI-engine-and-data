# Diagnosis API adapter

`route.ts` validates the demo's allow-listed KPI, region, category, and date parameters. It invokes `frontend_bridge.py` using the project virtual environment, parses its JSON, and returns it without caching.

This is a local-demo adapter rather than a production service: it starts a Python process for each request, has no authenticated caller identity, and has duplicated filter metadata. The review note lists the resulting scaling and security follow-ups.
