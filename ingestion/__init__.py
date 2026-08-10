"""Ingestion layer — the only place that talks to external data sources.

Phase 1 covers J-Quants (V2), EDINET DB and JSDA bond-trade statistics.
Local runtime is primary; Cloudflare reads storage only (Pattern B).
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
