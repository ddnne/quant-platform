# Features Registry

Phase 4 implements the **features** layer: a small, PIT-only, versioned
catalog of research features over Japanese-equity facts.

## Why a registry

A feature is a reusable, reproducible function from PIT-visible facts to a
typed value. The registry gives every feature:

* a stable **id** + **version** (semver-ish) so a downstream model can pin
  ``("return_1d", "1.0.0")`` and get the same value forever;
* a declared **input contract** (required kwargs, optional kwargs, as_of rule)
  so callers cannot silently drop a parameter;
* **PIT provenance** on every output (``as_of``, ``pit_api_version``,
  ``features_runtime_version``, ``db_path``, ``rows_seen``) so any value can
  be audited against the data that produced it.

## Contract (hard rules)

These mirror the **core** engine boundary. They are statically enforced by
``tests/test_features_data_boundary.py``.

* **Facts enter only via PIT.** Feature modules import :mod:`pit` and read
  through the ``FeatureContext`` PIT-scoped shortcuts. No ``sqlite3``,
  no :mod:`storage`, no HTTP client. The context publicly exposes only
  ``as_of`` and scoped getters: it has neither a ``db_path`` attribute nor a
  raw input mapping. Definitions retrieve one declared input at a time with
  ``ctx.get_input(...)``; the database scope remains in a runtime closure.
* **``as_of`` is required.** Every compute call passes an explicit
  ``as_of``; the runtime normalizes it via PIT's canonicalizer. There is no
  default — omitting it raises :class:`~features.runtime.AsOfRequired`.
* **Compute is pure.** A feature is a deterministic function of
  ``(registry entry, as_of, inputs, pit reads)``. No wall-clock time, no
  randomness, no global state.
* **Look-ahead is impossible.** PIT hides rows whose ``available_at > as_of``
  from the context's getters — features cannot see the future even if they
  try.

## Built-in features (v1.0.0)

| id             | inputs                 | intended_role | status    | description                                                  |
|----------------|------------------------|---------------|-----------|--------------------------------------------------------------|
| ``return_1d``  | ``code``               | ``signal``    | ``approved`` | One-session simple return (close-to-close) at ``as_of``.     |
| ``momentum_n`` | ``code``, ``n?``       | ``signal``    | ``approved`` | N-session cumulative return (default N=20).                  |
| ``volatility_n`` | ``code``, ``n?``     | ``signal``    | ``approved`` | N-session realized vol (sample stdev, √252 annualized, default N=20). |

Each returns ``FeatureOutput(value=None, metadata={...reason...})`` when
insufficient history is visible at ``as_of`` — that's a normal signal, not an
exception.

### Lifecycle metadata (P0-5)

Every :class:`FeatureDefinition` carries two required vocabulary fields so a
downstream model registry can decide what to ingest without reading the
compute function:

* **``intended_role``** — one of ``"signal"`` (model input), ``"state"``
  (regime / context), ``"structural"`` (universe / master-derived),
  ``"utility"`` (debug / diagnostic only). A model registry can refuse to
  ingest features whose role it does not support.
* **``status``** — promotion tier: ``"candidate"`` (unvetted),
  ``"shadow"`` (logged but not used), ``"approved"`` (default for
  shipped features), ``"retired"`` (kept for audit; do not consume in
  new code).

`intended_role` has no default and is required for every definition.
`status` defaults to ``"candidate"`` so a new or external feature is never
silently promoted. Shipped built-ins declare ``intended_role="signal"`` and
``status="approved"`` explicitly. Declarative strategies resolve features
through `features.get_for_strategy(...)`, which admits only approved,
strategy-facing roles by default; any override must be explicit.

### Price basis (F0-M)

Price-based definitions declare `price_basis="RAW"` and every output repeats
that value in provenance metadata. `RAW` means the PIT-visible, unadjusted
session close. `PIT_ADJUSTED` is reserved for a future series whose adjustment
factors and revisions can be reconstructed at each `as_of`; the existence of a
vendor `adjustment_close` field alone is not treated as PIT-safety evidence.
Core sizing, fills, marks, and the built-in price features therefore use the
same `RAW` convention.

## Usage

```python
from features import compute, compute_many, list_features, get

# Single feature
out = compute("return_1d",
              as_of="2025-04-03T15:30:00+09:00",
              code="8697",
              db_path="data/structured/ingestion.sqlite")
print(out.value, out.metadata["rows_seen"])

# Vector at one decision instant
vec = compute_many(
    ["return_1d", "momentum_n", "volatility_n"],
    as_of="2025-04-03T15:30:00+09:00",
    code="8697", n=10,
    db_path="data/structured/ingestion.sqlite",
)
for fid, o in vec.items():
    print(fid, o.value)

# Pin a version
feat = get("return_1d", version="1.0.0")
out = compute(feat, as_of=..., code=..., db_path=...)
```

## Adding a feature

```python
from features import register, FeatureDefinition, FeatureInput, FeatureVersion, FeatureOutput

def _my_feature(ctx):
    code = ctx.inputs["code"]
    bars = ctx.get_equity_bars_daily(code=code).rows
    if not bars:
        return FeatureOutput(value=None, metadata={"reason": "no bars"})
    last = bars[-1]
    return FeatureOutput(value=last["close"], metadata={"code": code,
                                                        "last_date": last["date"]})

register(FeatureDefinition(
    id="last_close",
    version=FeatureVersion(1, 0, 0),
    inputs=FeatureInput(required_kwargs=("code",), as_of_rule="session_close"),
    description="Last PIT-visible close at as_of.",
    compute=_my_feature,
    tags=("price",),
    intended_role="signal",   # or "state" / "structural" / "utility"
    status="candidate",       # or "shadow" / "approved" / "retired"
    price_basis="RAW",        # for price-derived definitions
))
```

## Phase 4 boundary rules

* **``features/`` does not import :mod:`risk`.** Risk is a separate layer
  (Phase 8). A risk module may *consume* features but not the reverse.
* **No mass agents, FoF, live broker, addon data** as a required input. The
  built-in features depend only on Premium core daily bars (in scope for the
  Phase 3.5 closed loop).
* **The registry never reads from disk or network at import time** — all
  reads happen inside ``compute`` via PIT.

## Reproducibility

Every output carries:

```
feature_id, feature_version, as_of,
pit_api_version, features_runtime_version,
db_path, rows_seen
```

Plus per-feature fields (e.g. ``prior_close``, ``n``, ``base_date``). Logging
the metadata alongside the value is enough to reproduce or audit any feature
call.

## Testing

* ``tests/test_features_data_boundary.py`` — static import ban + PIT-spy
  (no fact path leaks).
* ``tests/test_features_compute.py`` — built-in feature correctness,
  ``as_of``-required behavior, input validation, look-ahead guard, registry
  versioning, reproducibility.
* ``tests/test_phase4_real_db_smoke.py`` — F6: end-to-end
  ``run_backtest`` with a feature-driven strategy on a real-DB path.

Live smokes are marked ``@pytest.mark.live`` and skipped by default.
