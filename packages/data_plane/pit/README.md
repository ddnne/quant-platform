# pit

**Sole structured fact read path** for research compute.

## Public entry

```python
from pit import (
    get_equity_bars_daily,
    get_equity_master,
    get_market_calendar,
    get_jquants_records,
    get_jsda_bond_trades,
    get_jsda_repo_rates,
    PitError,
    PIT_API_VERSION,
)
```

Every `get_*` requires `as_of`. Rows with `available_at > as_of` or NULL are excluded. DB opens `mode=ro`.

## Allowed imports

- `ingestion` (path / catalog helpers only as needed)
- `storage` (schema awareness for reads)

## Forbidden

- Network / HTTP clients
- Writes to structured facts
- Importing `core` / `features` / `strategies` / product packages

Domain doc: [docs/pit_api.md](../../../docs/pit_api.md).
