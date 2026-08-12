# price_basis

Shared price-basis vocabulary for `features` and `core`.

## Public entry

```python
from price_basis import RAW, PIT_ADJUSTED, PriceBasis, require_supported_price_basis, UnsupportedPriceBasis
```

- `RAW` — only enabled basis (vendor unadjusted session price).
- `PIT_ADJUSTED` — reserved; **fail-closed** until PIT-versioned adjustment evidence exists.

## Allowed imports

- None (stdlib / typing only)

## Forbidden

- Assuming vendor “adjusted” columns are PIT-safe
- Opening SQLite / HTTP
