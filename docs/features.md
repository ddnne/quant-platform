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
  no :mod:`storage`, no HTTP client. The context exposes no DB handle.
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

| id             | inputs                 | description                                                  |
|----------------|------------------------|--------------------------------------------------------------|
| ``return_1d``  | ``code``               | One-session simple return (close-to-close) at ``as_of``.     |
| ``momentum_n`` | ``code``, ``n?``       | N-session cumulative return (default N=20).                  |
| ``volatility_n`` | ``code``, ``n?``     | N-session realized vol (sample stdev, √252 annualized, default N=20). |

Each returns ``FeatureOutput(value=None, metadata={...reason...})`` when
insufficient history is visible at ``as_of`` — that's a normal signal, not an
exception.

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
