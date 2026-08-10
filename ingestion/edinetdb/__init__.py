"""EDINET DB source.

Base: ``https://edinetdb.jp/v1`` — header ``X-API-Key``.

NOTE: EDINET DB's public API surface is not fully documented; this client
implements the paths named in the handoff (company list/detail, financials)
and normalizes defensively against whatever shape is returned. Exact field
names are documented as 仮 in ``docs/data_sources.md`` until confirmed live.

ToS: personal research use only; respect EDINET DB terms.
"""
