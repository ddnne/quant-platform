# W63 / w0815bd — Multi-year data availability table

**Purpose:** Document year windows and dataset holes without invent densify.

| period_id | year | bars status | topix source | calendar source | s4/margin | n_days S1 |
|-----------|-----:|-------------|--------------|-----------------|-----------|----------:|
| y2015_q4 | 2015 | ok | archive (jsonl_gap=False) | archive+PIT | ok | 50 |
| y2017_q4 | 2017 | ok | archive (jsonl_gap=False) | archive+PIT | ok | 50 |
| y2019_q4 | 2019 | ok | archive (jsonl_gap=False) | archive+PIT | ok | 50 |
| y2021_q4 | 2021 | ok | archive (jsonl_gap=False) | archive+PIT | ok | 50 |
| y2023_q4 | 2023 | ok | archive (jsonl_gap=False) | archive+PIT | ok | 50 |
| y2025_q4 | 2025 | ok | archive (jsonl_gap=True) | archive+PIT | ok | 50 |

### Inventory notes (held from W61)

- bars JSONL: 2008–2026
- topix JSONL: **gap 2024–2025** → archive
- calendar JSONL: tip 2026 only → archive + PIT repair
- margin JSONL: **gap 2024** empty_allowed — never invent

Year list intentionally omits 2024 so S4 is not forced over an empty inventory year.

