---
name: verify
description: how to run and drive delvefall locally for verification
---

# Run

DATABASE_URL comes from .env in the repo root (the railway database, the
only one there is). Dev server:

    $env:DATABASE_URL = (Get-Content .env) -replace 'DATABASE_URL=',''
    python web\app.py

Serves http://127.0.0.1:5000 in a few seconds.

# Drive

- search page: /search?q=Lightning+Bolt plus any filter params (sort, min,
  blend, cur, colors...)
- load more json: /more?q=...&offset=20 with the same params, weak=1 pages
  the weak tier
- result names in the html: `<div class="result-name">NAME <span`
- schema changes: the app selects new card columns unconditionally, so run
  the ALTER from common/schema.sql against the database before starting or
  every search 500s. ingest runs schema.sql daily so prod self-heals

# Gotchas

- the ingest is too heavy to run whole locally (2gb download plus the
  embedding model from a private hf repo). its pure scan functions import
  fine without torch: `from ingest.update import cheapest_prices`
- ide diagnostics on search.html are noise, the ts service can't read
  jinja inside script tags
