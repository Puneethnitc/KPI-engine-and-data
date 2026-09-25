# Frontend handoff inbox

Place the downloaded v0 export here as:

```text
imports/v0-frontend.zip
```

Do not extract it over `finalkpi/frontend/`. The integration workflow is:

1. Preserve the ZIP unchanged as the source handoff.
2. Extract it into a temporary review directory.
3. compare its framework, dependencies, routes, components, and assets with
   `finalkpi/frontend/`.
4. Port the approved presentation components into the existing frontend while
   retaining the backend-bound data layer and repository instructions.

Everything in this directory except this README is ignored by Git so downloaded
archives and temporary exports cannot be committed accidentally.
