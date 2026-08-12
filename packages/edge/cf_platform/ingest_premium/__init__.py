"""Phase 3.5 — Premium core ingestion closed loop (Python mirror).

The Cloudflare Worker (`platform/workers/ingestion-premium/`) owns the live
schedule. This package mirrors the **logic** (dataset set, validation rules,
run summary shape) so:

* tests can assert the closed-loop contract offline (no network);
* the local sync script and ops tooling share one source of truth;
* Codex review can read Python instead of TypeScript to verify behaviour.

Nothing in this package performs network I/O. It is pure transformation and
validation.
"""
