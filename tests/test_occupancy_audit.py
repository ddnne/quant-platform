"""Occupancy maps / wave pack. Does not GO. Does not apply reconstitution."""
from __future__ import annotations


def test_usable_eval_snapshot_is_not_a_pass() -> None:
    from research.occupancy_audit import usable_eval_snapshot

    snap = usable_eval_snapshot({"mid_n_explore": {}, "liq_large": {}})
    assert snap["go"] is False
    assert snap["not_a_pass"] is True
    assert snap["inventory"]["version"] == "usable-inventory/v1"
    assert snap["usable_read"]["version"] == "usable-read/v3"
    assert snap["usable_read"]["do_not_silent_unpark"] is True
    assert snap["cost_risk"]["fake_split"] is False
    assert snap["cost_risk"]["not_a_pass"] is True
    assert snap["series"]["version"] == "usable-series/v1"
    assert snap["series"]["go"] is False


def test_write_usable_eval_snapshot_local_only(tmp_path) -> None:
    from research.occupancy_audit import write_usable_eval_snapshot

    out = write_usable_eval_snapshot(
        {"mid_n_explore": {}, "liq_large": {}},
        wave="test24em",
        root=tmp_path,
        put_r2=False,
    )
    assert out["go"] is False
    assert out["yaml_remains_sot"] is True
    assert out["puts"] == []
    assert (tmp_path / "eval-usable-inventory-test24em.json").is_file()
    assert (tmp_path / "eval-combo-jsonl-test24em.jsonl").is_file()


def test_write_eval_wave_pack_local_only(tmp_path) -> None:
    import json

    from research.occupancy_audit import write_eval_wave_pack

    out = write_eval_wave_pack(
        {"mid_n_explore": {"x": 0.4}, "liq_large": {"x": 0.41}},
        wave="test24ep",
        root=tmp_path,
        put_r2=False,
    )
    assert out["go"] is False
    assert out["not_a_pass"] is True
    assert out["catalog_and_plus_n_stopped"] is True
    assert out["reconstitution_apply"] is False
    assert out["n_unique22_parked"] >= 1
    assert out["occupancy_maps_job"] == "eval-occupancy-maps-test24ep"
    assert out["series_sleeve_job"] == "eval-series-sleeve-test24ep"
    assert (tmp_path / "eval-occupancy-maps-test24ep.json").is_file()
    assert (tmp_path / "eval-occupancy-drift-test24ep.json").is_file()
    assert (tmp_path / "eval-unique22-park-test24ep.json").is_file()
    assert (tmp_path / "eval-reconstitution-plan-test24ep.json").is_file()
    assert (tmp_path / "eval-series-sleeve-test24ep.json").is_file()
    recon = json.loads(
        (tmp_path / "eval-reconstitution-plan-test24ep.json").read_text(
            encoding="utf-8"
        )
    )
    fund = next(
        s for s in recon["sleeves"] if s["basket_id"] == "basket_theme_fund"
    )
    assert recon["apply"] is False
    assert isinstance(fund["nested_parent_count"], int)
    assert fund["nested_parent_count"] >= 1
    assert fund["nested_pairs"]
    preview = recon["occupancy_preview"]
    assert preview["apply"] is False
    assert preview["do_not_restitch_blend"] is True
    assert preview["human_choice_required"] is True
    assert "basket_theme_fund" in preview["human_pending"]
    assert preview["keep_sleeves_job"] == "eval-cf-dp-both-sleeves-20260824df"
    prev_fund = next(
        s for s in preview["sleeves"] if s["basket_id"] == "basket_theme_fund"
    )
    assert prev_fund["apply"] is False
    assert prev_fund["current"]["occupancy_mean_not_a_blend"] is True
    sleeve = json.loads(
        (tmp_path / "eval-series-sleeve-test24ep.json").read_text(encoding="utf-8")
    )
    assert sleeve["apply"] is False
    assert sleeve["invert_primary"] is False
    assert sleeve["go"] is False


def test_merge_occupancy_cell_dumps_later_mtime_wins(tmp_path) -> None:
    import json
    import time

    from research.occupancy_audit import merge_occupancy_cell_dumps

    old = [{"logic_id": "x", "occupancy": 0.2}]
    new = [{"logic_id": "x", "occupancy": 0.5}]
    older = tmp_path / "eval-occupancy-audit-z-mid_n_explore_cells.json"
    newer = tmp_path / "eval-occupancy-audit-a-mid_n_explore_cells.json"
    older.write_text(json.dumps(old), encoding="utf-8")
    time.sleep(0.05)
    newer.write_text(json.dumps(new), encoding="utf-8")
    (tmp_path / "eval-occupancy-audit-a-liq_large_cells.json").write_text(
        json.dumps(new), encoding="utf-8"
    )
    out = merge_occupancy_cell_dumps(tmp_path)
    assert out["mid_n_explore"]["x"] == 0.5
    assert out["liq_large"]["x"] == 0.5


def test_load_ops_occupancy_prefers_maps_over_cells(tmp_path) -> None:
    import json

    from research.occupancy_audit import load_ops_occupancy, write_eval_wave_pack

    cells = [{"logic_id": "old", "occupancy": 0.2}]
    (tmp_path / "eval-occupancy-audit-x-mid_n_explore_cells.json").write_text(
        json.dumps(cells), encoding="utf-8"
    )
    (tmp_path / "eval-occupancy-audit-x-liq_large_cells.json").write_text(
        json.dumps(cells), encoding="utf-8"
    )
    write_eval_wave_pack(
        {"mid_n_explore": {"new": 0.3}, "liq_large": {"new": 0.31}},
        wave="testmaps",
        root=tmp_path,
        put_r2=False,
    )
    occ = load_ops_occupancy(tmp_path)
    assert occ["mid_n_explore"]["new"] == 0.3
    assert "old" not in occ["mid_n_explore"]


def test_load_ops_occupancy_overlays_newer_cells(tmp_path) -> None:
    import json
    import time

    from research.occupancy_audit import load_ops_occupancy, write_eval_wave_pack

    write_eval_wave_pack(
        {"mid_n_explore": {"old": 0.2}, "liq_large": {"old": 0.21}},
        wave="testold",
        root=tmp_path,
        put_r2=False,
    )
    time.sleep(0.05)
    newer = [{"logic_id": "fresh", "occupancy": 0.4}]
    (tmp_path / "eval-occupancy-audit-z-mid_n_explore_cells.json").write_text(
        json.dumps(newer), encoding="utf-8"
    )
    (tmp_path / "eval-occupancy-audit-z-liq_large_cells.json").write_text(
        json.dumps(newer), encoding="utf-8"
    )
    occ = load_ops_occupancy(tmp_path)
    assert occ["mid_n_explore"]["old"] == 0.2
    assert occ["mid_n_explore"]["fresh"] == 0.4
    assert occ["liq_large"]["old"] == 0.21
    assert occ["liq_large"]["fresh"] == 0.4


def test_run_eval_wave_local_stub_never_writes(tmp_path) -> None:
    from research.occupancy_audit import run_eval_wave

    def _invoke(**_kwargs):
        return {
            "ok": False,
            "error": "llm_failed",
            "n_adoptable": 0,
            "proposals": [],
            "reviews": [],
        }

    out = run_eval_wave(
        {"mid_n_explore": {"x": 0.4}, "liq_large": {"x": 0.4}},
        wave="test24eq",
        root=tmp_path,
        put_r2=False,
        propose=True,
        invoke=_invoke,
    )
    assert out["go"] is False
    assert out["catalog_written"] is False
    assert out["auto_inject"] is False
    assert out["propose"]["written"] is False
    assert out["propose"]["llm_failed_not_soup"] is True
    assert (tmp_path / "eval-occupancy-maps-test24eq.json").is_file()
    assert (tmp_path / "eval-cf-propose-test24eq.json").is_file()


def test_merge_daily_path_cells_for_ids_later_file_wins(tmp_path) -> None:
    import json

    from research.occupancy_audit import merge_daily_path_cells_for_ids

    a = {
        "logic_id": "x",
        "window_id": "w0",
        "net_daily": [0.0, 0.01],
        "occupancy": 0.2,
    }
    b = dict(a)
    b["occupancy"] = 0.4
    (tmp_path / "eval-a-mid_n_explore_cells.json").write_text(
        json.dumps([a]), encoding="utf-8"
    )
    (tmp_path / "eval-b-mid_n_explore_cells.json").write_text(
        json.dumps([b]), encoding="utf-8"
    )
    (tmp_path / "eval-c-liq_large_cells.json").write_text(
        json.dumps([a]), encoding="utf-8"
    )
    out = merge_daily_path_cells_for_ids(tmp_path, ["x"])
    assert len(out["mid_n_explore"]) == 1
    assert out["mid_n_explore"][0]["occupancy"] == 0.4
    assert len(out["liq_large"]) == 1
