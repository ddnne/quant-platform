"""JSDA bond-trade statistics source.

Reference index: https://www.jsda.or.jp/shiryoshitsu/toukei/saiken_torihiki/

Files are published as CSV/XLSX and the exact URLs change over time, so URL
resolution is isolated in :mod:`urls` and parsing in :mod:`parse`. JSDA is
**local-preferred** in Phase 1 (HTML scraping from a Japanese gov-adjacent
site risks bot/DC challenges from the edge — not suitable for Cloudflare
fetch). See ``docs/data_sources.md`` for the column map.

ToS: cite the source; personal research use.
"""
