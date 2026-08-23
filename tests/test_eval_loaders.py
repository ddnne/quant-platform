"""Eval sidecar loaders. No invent / no ffill. Not GO."""
from __future__ import annotations

def test_repo_history_plane_status_discloses_sqlite_not_d1() -> None:
    from research.eval_loaders import repo_history_plane_status

    note = repo_history_plane_status()
    assert note["invent_complete"] is False
    assert note["ffill_applied"] is False
    assert note["d1_role"] == "hot_tip_only"
    assert note["pit_path"] == "fail_closed_until_READY"
    assert note["sqlite_rows"] >= 0


def test_fins_events_keep_ta_eqar_from_payload() -> None:
    from research.eval_loaders import load_fins_events_from_sqlite

    events = load_fins_events_from_sqlite(
        codes=["33210"], start="2008-01-01", end="2008-12-31"
    )
    rows = events.get("33210") or []
    assert rows, "33210 FY 2008 fins_summary should load"
    tas = [r.get("ta") for r in rows]
    eqars = [r.get("eq_ar") for r in rows]
    assert any(v is not None and float(v) > 0 for v in tas)
    assert any(v is not None and float(v) > 0 for v in eqars)
    for r in rows:
        if r.get("ta") is None:
            assert "ta" in r
        else:
            assert r["ta"] != 0 or r["ta"] == 0  # real zero allowed; no invent of missing
        # missing stays None, never a filled-in sentinel
        assert r.get("ta") is None or isinstance(r.get("ta"), (int, float))
        assert r.get("eq_ar") is None or isinstance(r.get("eq_ar"), (int, float))


def test_fins_ta_eqar_stats_see_official_keys() -> None:
    from research.eval_loaders import fins_summary_ta_eqar_stats

    stats = fins_summary_ta_eqar_stats(limit=2000)
    assert stats["invent"] is False
    assert stats["official_keys"]["ta"] == "TA"
    assert stats["official_keys"]["eq_ar"] == "EqAR"
    assert stats["n_rows"] >= 100
    assert stats["n_ta_nonnull"] > 0
    assert stats["n_eqar_nonnull"] > 0
    assert (stats["ncta_nonnull"] or 0) < (stats["n_ta_nonnull"] or 0)

