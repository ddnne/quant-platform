"""Ingestion layer — the only place that talks to external data sources.

Phase 1 covers J-Quants (V2) and JSDA bond-trade statistics. Disclosure-style
data is sourced via J-Quants' EDINET-family APIs in a later phase, not a
standalone EDINET DB. Local runtime is primary; Cloudflare reads storage only
(Pattern B).
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
