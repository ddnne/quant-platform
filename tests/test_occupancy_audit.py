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

def test_unique22_lift_park_partition() -> None:
    from research.unique_logic.worker_bodies import (
        unique22_occupancy_equal_lifted,
        unique22_occupancy_park,
        unique_leftover_logic_ids,
    )

    leftover = unique_leftover_logic_ids()
    lifted = unique22_occupancy_equal_lifted()
    parked = unique22_occupancy_park()
    from research.unique_logic.worker_bodies import UNIQUE22_PARK_REASONS

    assert lifted | parked == leftover
    assert lifted.isdisjoint(parked)
    assert "event_pre_mom_agree_hold" in parked
    assert "afterclose_only_event_hold" in lifted
    assert set(UNIQUE22_PARK_REASONS) == set(parked)
    assert "momentumAt(entryIdx)" in UNIQUE22_PARK_REASONS["event_pre_mom_agree_hold"]


def test_near_empty_park_is_not_countable_or_basket_material() -> None:
    from research.combo_basket_catalog import validate_basket_members
    from research.unique_logic.constants import (
        CANDIDATE_POLICY,
        NEAR_EMPTY_OCCUPANCY,
        NEAR_EMPTY_PARK_IDS,
    )
    from research.unique_logic.worker_bodies import (
        NearEmptyBatchError,
        assert_new_batch_occupancy_not_near_empty,
        countable_thesis_ids,
        is_countable_spec,
        near_empty_occupancy_park,
    )
    from research.unique_logic.catalog import catalog_spec

    parked = near_empty_occupancy_park()
    assert parked == NEAR_EMPTY_PARK_IDS
    assert parked
    assert "surprise_xs_fy_end" in parked
    assert "event_roe_low_fade" in parked
    assert "cs_roe_low" in parked
    countable = countable_thesis_ids()
    for lid in parked:
        spec = catalog_spec(lid)
        assert spec is not None
        assert is_countable_spec(spec) is False
        assert lid not in countable
    reasons = validate_basket_members(
        ["event_eqar_high_liq_high", next(iter(parked))]
    )
    assert "near_empty_member" in reasons
    from research.unique_logic.constants import THIN_SLEEVE_EXCLUDE_IDS
    from research.cf_daily_path_job import sleeve_durability_logic_ids

    assert THIN_SLEEVE_EXCLUDE_IDS
    assert "surprise_xs_pb_rising_crowded" in THIN_SLEEVE_EXCLUDE_IDS
    assert "event_margin_up_steep_curve" in THIN_SLEEVE_EXCLUDE_IDS
    assert "event_liq_high_steep_curve" in THIN_SLEEVE_EXCLUDE_IDS
    assert "event_np_easing" in THIN_SLEEVE_EXCLUDE_IDS
    assert "event_ease_p10" in THIN_SLEEVE_EXCLUDE_IDS
    assert "event_r3m_steep" in THIN_SLEEVE_EXCLUDE_IDS
    assert "event_eql_steep" in THIN_SLEEVE_EXCLUDE_IDS
    assert "surprise_xs_div_p10" in NEAR_EMPTY_PARK_IDS
    assert THIN_SLEEVE_EXCLUDE_IDS.isdisjoint(NEAR_EMPTY_PARK_IDS)
    assert THIN_SLEEVE_EXCLUDE_IDS.isdisjoint(sleeve_durability_logic_ids())
    thin_reasons = validate_basket_members(
        ["event_eqar_high_liq_high", "event_p10_pb_rising"]
    )
    assert "thin_sleeve_member" in thin_reasons
    assert "event_p10_pb_rising" in countable_thesis_ids()
    assert "near_empty_parked" in CANDIDATE_POLICY["exclude"]
    occ = {lid: 0.20 for lid in ("a", "b", "c")}
    ok = assert_new_batch_occupancy_not_near_empty(occ)
    assert ok["ok"] is True
    assert ok["n_near_empty"] == 0


def test_usable_inventory_excludes_thin_park_and_unclassified() -> None:
    from research.unique_logic.constants import (
        NEAR_EMPTY_PARK_IDS,
        THIN_SLEEVE_EXCLUDE_IDS,
        USABLE_OCCUPANCY_MIN,
    )
    from research.unique_logic.worker_bodies import usable_inventory

    lid = "event_eqar_high_liq_high"
    thin = next(iter(THIN_SLEEVE_EXCLUDE_IDS))
    park = next(iter(NEAR_EMPTY_PARK_IDS))
    pack = usable_inventory(
        {
            "mid_n_explore": {lid: 0.30, thin: 0.30, park: 0.30},
            "liq_large": {lid: 0.31, thin: 0.31, park: 0.31},
        }
    )
    assert pack["go"] is False
    assert pack["not_a_pass"] is True
    assert pack["usable_occupancy_min"] == USABLE_OCCUPANCY_MIN
    assert lid in pack["usable_ids"]
    assert thin not in pack["usable_ids"]
    assert park not in pack["usable_ids"]
    assert pack["n_usable"] >= 1
    assert "event" in pack["family"]


def test_classify_occupancy_pair_bands() -> None:
    from research.occupancy_audit import classify_occupancy_maps
    from research.occupancy_guards import classify_occupancy_pair

    assert classify_occupancy_pair(0.00, 0.02) == "near_empty_park"
    assert classify_occupancy_pair(0.0496, 0.0670) == "thin_sleeve_exclude"
    assert classify_occupancy_pair(0.08, 0.11) == "thin_sleeve_exclude"
    assert classify_occupancy_pair(0.1164, 0.1206) == "thin_sleeve_exclude"
    assert classify_occupancy_pair(0.30, 0.31) == "material"
    assert classify_occupancy_pair(0.90, 0.91) == "always_on_park"
    assert classify_occupancy_pair(0.40, 0.90) == "mixed_always"
    assert classify_occupancy_pair(0.30, None) == "unclassified"
    assert classify_occupancy_pair(None, 0.30) == "unclassified"
    pack = classify_occupancy_maps(
        {
            "mid_n_explore": {"a": 0.00, "b": 0.30, "c": 0.10},
            "liq_large": {"a": 0.01, "b": 0.31, "c": 0.11},
        },
        ["a", "b", "c", "d"],
    )
    assert pack["go"] is False
    assert pack["by_band"]["near_empty_park"] == ["a"]
    assert pack["by_band"]["material"] == ["b"]
    assert pack["by_band"]["thin_sleeve_exclude"] == ["c"]
    assert pack["by_band"]["unclassified"] == ["d"]
    from research.occupancy_audit import occupancy_recorded_drift

    drift = occupancy_recorded_drift(
        {
            "mid_n_explore": {"a": 0.00, "b": 0.30},
            "liq_large": {"a": 0.01, "b": 0.31},
        },
        ["a", "b"],
    )
    assert drift["go"] is False
    assert drift["do_not_silent_unpark"] is True
    assert "a" in drift["empty_not_recorded"]


def test_near_empty_batch_guard_and_park_sparse_cover() -> None:
    from pathlib import Path
    import json
    from research.unique_logic.constants import NEAR_EMPTY_OCCUPANCY
    from research.unique_logic.worker_bodies import (
        NearEmptyBatchError,
        assert_near_empty_park_covers,
        assert_new_batch_occupancy_not_near_empty,
        mean_occupancy_by_logic,
    )

    try:
        assert_new_batch_occupancy_not_near_empty(
            {"ok_one": 0.20, "empty_one": NEAR_EMPTY_OCCUPANCY}
        )
        raise AssertionError("near_empty batch must reject")
    except NearEmptyBatchError:
        pass

    cells_path = (
        Path(__file__).resolve().parents[1]
        / "data"
        / "ops"
        / "research_eval"
        / "eval-cf-dp-liq100-plus32vf-20260823h_cells.json"
    )
    if cells_path.is_file():
        occ_map = mean_occupancy_by_logic(json.loads(cells_path.read_text(encoding="utf-8")))
        cover = assert_near_empty_park_covers(occ_map)
        assert cover["ok"] is True
        assert cover["n_recorded"] >= 4
        assert cover["missing_from_park"] == []

    from research.unique_logic.catalog import catalog_spec
    from research.unique_logic.constants import NEAR_EMPTY_PARK_IDS, SPARSE_GATE_COMBOS

    sparse = [combo for combo, _ in SPARSE_GATE_COMBOS]
    for lid in NEAR_EMPTY_PARK_IDS:
        spec = catalog_spec(lid)
        params = spec.get("params") if isinstance(spec.get("params"), dict) else {}
        gates = frozenset(str(g) for g in (params.get("gates") or []) if str(g).strip())
        if not gates:
            continue
        assert any(combo <= gates for combo in sparse), (
            f"{lid} parked empty but no SPARSE_GATE_COMBOS subset covers {sorted(gates)}"
        )


def test_thin_or_parked_two_and_is_sparse_parent() -> None:
    from research.cf_propose_thesis import review_proposal_row
    from research.unique_logic.constants import SPARSE_GATE_COMBOS

    parent = frozenset({"eps_down", "steep_curve"})
    assert any(combo == parent for combo, _ in SPARSE_GATE_COMBOS)
    nested = {
        "thesis": (
            "PEAD when EPS contracted versus the last prior print AND "
            "the repo curve is steep AND overnight funding is tight. "
            "Skip missing PIT prints (no invent)."
        ),
        "signal_definition": "AND(eps_down, steep_curve, tight_funding) PIT",
        "position_rule": "event-hold surprise sign",
        "datasets": [
            "equities_bars_daily",
            "fins_summary",
            "markets_calendar",
            "jsda_tokyo_repo_rates",
        ],
        "gates": ["eps_down", "steep_curve", "tight_funding"],
    }
    rev = review_proposal_row(nested)
    assert rev["ok"] is False
    assert "sparse_gate_combo" in rev["reasons"]
    assert rev["auto_inject"] is False


def test_always_on_batch_guard_and_empty_park() -> None:
    from research.combo_basket_catalog import validate_basket_members
    from research.unique_logic.constants import (
        ALWAYS_ON_OCCUPANCY_WARN,
        ALWAYS_ON_PARK_IDS,
        CANDIDATE_POLICY,
    )
    from research.unique_logic.worker_bodies import (
        AlwaysOnBatchError,
        always_on_occupancy_park,
        assert_new_batch_occupancy_in_material_band,
        assert_new_batch_occupancy_not_always_on,
        countable_thesis_ids,
    )

    assert always_on_occupancy_park() == ALWAYS_ON_PARK_IDS
    assert "cs_ta_up" in ALWAYS_ON_PARK_IDS
    assert "cs_ta_down" in ALWAYS_ON_PARK_IDS
    assert "cs_np_positive" in ALWAYS_ON_PARK_IDS
    assert "always_on_parked" in CANDIDATE_POLICY["exclude"]
    assert ALWAYS_ON_PARK_IDS.isdisjoint(countable_thesis_ids())
    ok = assert_new_batch_occupancy_not_always_on(
        {"a": 0.20, "b": 0.40, "c": 0.30}
    )
    assert ok["ok"] is True
    assert ok["n_always_on"] == 0
    try:
        assert_new_batch_occupancy_not_always_on(
            {"ok_one": 0.20, "sticky": ALWAYS_ON_OCCUPANCY_WARN}
        )
        raise AssertionError("always_on batch must reject")
    except AlwaysOnBatchError:
        pass
    band = assert_new_batch_occupancy_in_material_band(
        {"a": 0.20, "b": 0.40}
    )
    assert band["ok"] is True
    try:
        assert_new_batch_occupancy_in_material_band({"sticky": 0.90})
        raise AssertionError("material band must reject always_on")
    except AlwaysOnBatchError:
        pass
    if ALWAYS_ON_PARK_IDS:
        reasons = validate_basket_members(
            ["event_eqar_high_liq_high", next(iter(ALWAYS_ON_PARK_IDS))]
        )
        assert "always_on_member" in reasons
