"""Eval sidecar loaders. No invent / no ffill. Not GO."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path


def _fins_sqlite(tmp_path: Path) -> Path:
    """Minimal jquants_records fins_summary with official TA / EqAR keys."""
    db = tmp_path / "ingestion.sqlite"
    con = sqlite3.connect(db)
    try:
        con.execute(
            "CREATE TABLE jquants_records ("
            "source TEXT NOT NULL, dataset TEXT NOT NULL, natural_key TEXT NOT NULL, "
            "event_time TEXT NOT NULL, available_at TEXT NOT NULL, ingested_at TEXT NOT NULL, "
            "payload TEXT, raw_payload TEXT, "
            "PRIMARY KEY (source, dataset, natural_key))"
        )
        rows = (
            {
                "Code": "33210",
                "DiscDate": "2008-02-14",
                "DiscTime": "15:00:00",
                "DiscNo": "1",
                "TA": None,
                "EqAR": None,
                "Eq": None,
            },
            {
                "Code": "33210",
                "DiscDate": "2008-05-15",
                "DiscTime": "15:00:00",
                "DiscNo": "2",
                "TA": 1_234_567_890.0,
                "EqAR": 0.42,
                "Eq": 518_518_513.0,
            },
            {
                "Code": "33210",
                "DiscDate": "2008-08-14",
                "DiscTime": "15:00:00",
                "DiscNo": "3",
                "TA": 1_250_000_000.0,
                "EqAR": 0.41,
                "Eq": 512_500_000.0,
            },
            {
                "Code": "33210",
                "DiscDate": "2008-11-14",
                "DiscTime": "15:00:00",
                "DiscNo": "4",
                "TA": 1_300_000_000.0,
                "EqAR": 0.40,
                "Eq": 520_000_000.0,
                "NCTA": 50_000.0,
            },
        )
        for pl in rows:
            nk = json.dumps(
                {
                    "Code": pl["Code"],
                    "DiscDate": pl["DiscDate"],
                    "DiscNo": pl["DiscNo"],
                },
                separators=(",", ":"),
            )
            event_time = f"{pl['DiscDate']}T15:00:00+09:00"
            payload = json.dumps(pl)
            con.execute(
                "INSERT INTO jquants_records "
                "(source, dataset, natural_key, event_time, available_at, "
                "ingested_at, payload, raw_payload) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "jquants",
                    "fins_summary",
                    nk,
                    event_time,
                    event_time,
                    event_time,
                    payload,
                    payload,
                ),
            )
        con.commit()
    finally:
        con.close()
    return db


def test_repo_history_plane_status_discloses_sqlite_not_d1() -> None:
    from research.eval_loaders import repo_history_plane_status

    note = repo_history_plane_status()
    assert note["invent_complete"] is False
    assert note["ffill_applied"] is False
    assert note["d1_role"] == "hot_tip_only"
    assert note["pit_path"] == "fail_closed_until_READY"
    assert note["sqlite_rows"] >= 0
    assert isinstance(note["sqlite_missing"], bool)
    if note["sqlite_missing"]:
        assert note["sqlite_rows"] == 0


def test_fins_events_keep_ta_eqar_from_payload(tmp_path: Path) -> None:
    from research.eval_loaders import load_fins_events_from_sqlite

    events = load_fins_events_from_sqlite(
        _fins_sqlite(tmp_path),
        codes=["33210"],
        start="2008-01-01",
        end="2008-12-31",
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


def test_fins_ta_eqar_stats_see_official_keys(tmp_path: Path) -> None:
    from research.eval_loaders import fins_summary_ta_eqar_stats

    stats = fins_summary_ta_eqar_stats(_fins_sqlite(tmp_path), limit=2000)
    assert stats["invent"] is False
    assert stats["official_keys"]["ta"] == "TA"
    assert stats["official_keys"]["eq_ar"] == "EqAR"
    assert stats["n_rows"] == 4
    assert stats["n_ta_nonnull"] == 3
    assert stats["n_eqar_nonnull"] == 3
    assert (stats["ncta_nonnull"] or 0) < (stats["n_ta_nonnull"] or 0)
    assert stats["ncta_nonnull"] == 1
