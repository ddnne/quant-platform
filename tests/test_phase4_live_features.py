"""Phase 4 B1 — feature compute smoke (offline fixtures; live via QP_LIVE=1)."""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

import features
from cf_platform.live_gates import b0_pass


def _many_days(n: int = 30) -> list[str]:
    # Synthetic weekdays March 2025
    days: list[str] = []
    for d in range(3, 31):
        # skip weekend-ish: 1=Sun pattern simple
        if d % 7 in (1, 2):
            continue
        days.append(f"2025-03-{d:02d}")
        if len(days) >= n:
            break
    return days


@pytest.fixture
def multi_db(tmp_path):
    from tests._coreseed import seed_db

    days = _many_days(25)
    codes = [f"{1000+i}" for i in range(10)]
    prices = {
        c: {d: 100.0 + i + j * 0.5 for j, d in enumerate(days)}
        for i, c in enumerate(codes)
    }
    path = seed_db(tmp_path, codes=codes, days=days, prices=prices)
    return path, days, codes


def test_b0_metrics_report_offline(multi_db):
    db, _, _ = multi_db
    ok, results = b0_pass(db, strict=False)
    assert ok is True
    assert any(r.name == "B0_master" for r in results)
    ok_strict, _ = b0_pass(db, strict=True)
    assert ok_strict is False


def test_features_majority_non_null(multi_db):
    db, days, codes = multi_db
    as_of = f"{days[-1]}T15:30:00+09:00"
    ids = ("return_1d", "momentum_n", "volatility_n")

    def one(code: str):
        out = {}
        for fid in ids:
            try:
                r = features.compute(fid, as_of=as_of, code=code, db_path=db)
                out[fid] = getattr(r, "value", None)
            except Exception as exc:  # noqa: BLE001
                out[fid] = f"ERR:{type(exc).__name__}"
        return code, out

    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = [f.result() for f in as_completed([pool.submit(one, c) for c in codes])]
    non_null = sum(
        1 for _, vals in rows if any(isinstance(v, (int, float)) for v in vals.values())
    )
    assert non_null >= max(1, len(codes) // 2), rows


@pytest.mark.live
def test_live_b0_and_features_sample():
    if os.environ.get("QP_LIVE") != "1":
        pytest.skip("QP_LIVE!=1")
    db = Path(os.environ.get("QP_DB", "data/structured/ingestion.sqlite"))
    if not db.exists():
        pytest.skip(f"no DB at {db}")
    ok, results = b0_pass(db, strict=True)
    assert ok, [r.as_dict() for r in results]
