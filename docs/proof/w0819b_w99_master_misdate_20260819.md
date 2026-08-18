# W99 / w0819b Track D — equities_master MISDATE optional re-probe

**Wave:** W99 / `w0819b` · Track D  
**Dataset:** `equities_master`  
**Scope:** MISDATE `2006-08…2008-04` only (PRE_PLAN already de-scoped in W98)  
**Artifacts:** [`.glm-logs/w0819b_w99_otc_sticky_dd/`](../../.glm-logs/w0819b_w99_otc_sticky_dd/)  
**Implementer:** GLM5.3 only. Grok did **not** implement.

---

## Verdict

| Check | Result |
|-------|--------|
| Optional re-probe | **ran** |
| In-window `Date` | **none** (`window_ok=0` / prior cache NO_IN_WINDOW_DATE) |
| Seal | **0** — KEEP PARTIAL |
| COMPLETE | **220** held |
| PARTIAL (MISDATE) | **21** held |
| POST_ISLAND holes | **0** |
| Floor raise to 2008-05 | **FORBIDDEN / not done** |
| Dataset status | **PARTIAL** held |

**No change.** Seal only if valid in-window Date appears; it did not.

---

## Policy held

- PRE_PLAN remains coverage out-of-scope (W98 de-scope)  
- MISDATE stays honest PARTIAL until vendor returns in-window Date  
- Never raise subscription/catalog floor to fake COMPLETE  
- empty COMPLETE **0**
