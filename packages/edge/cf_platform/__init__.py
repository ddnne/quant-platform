"""Cloudflare platform helpers shared between Workers and Python tooling.

Named ``cf_platform`` because ``platform`` is a Python stdlib module — we
keep this top-level package distinct from both the stdlib name and the
``platform/`` directory (which holds Worker wrangler configs and is not a
package).

The Python half of the Phase 3.5 closed loop lives here:
* :mod:`cf_platform.ingest_premium.validate` — pass/fail classification,
  required-dataset coverage, addon-exclusion helpers.
* :mod:`cf_platform.ingest_premium.natural_key` — natural-key + event-time
  extraction shared with the TypeScript Worker.

The TypeScript Worker sources live at ``platform/workers/ingestion-premium/``.
"""
