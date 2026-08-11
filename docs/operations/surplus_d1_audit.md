# Surplus D1 audit

**Source:** GLM Worker4 (`GLM_W4_D1INV_OK`)  
**Date:** 2026-08-11  

| name | uuid | role | keep/retire | action |
|------|------|------|-------------|--------|
| quant-ingest | be6fdcf8-40be-41fc-9535-7facd1fc2ffc | quant control/evidence/hot | **KEEP** | prune/rotate structured cold → R2 |
| news-db | 4b871136-73e0-42f1-97db-e1eb707ca057 | news product | **KEEP isolated** | never bind into quant workers |

## Conclusion

- **No surplus quant D1 to delete today.**  
- Anti-pattern: creating year/table/dataset-split D1 for capacity — use R2 instead.  
- news-db stays product-isolated (YES).

## 2026-08-12 follow-up (live quant-ingest)

| action | detail |
|--------|--------|
| Cleared nk_v2 stage tables | primary/revisions/versions + change_log stage (migration READY) |
| Dropped empty legacy | jquants_daily_bars(+rev), listed_info(+rev), market_calendar(+rev) |
| D1 size after | ~651.86 MB |
| table count | 31 |
| cold bars on remote | 0 |

No additional quant D1 databases to delete. news-db remains isolated.
