"""Reconstitution evidence pack. Apply stays False. Both options exist."""
from __future__ import annotations

import json

import pytest


KEEP_FUND = (
    "event_ta_up_positive_eps",
    "event_large_surprise_positive_eps",
    "event_ac_peps_taup",
    "event_eqar_high_positive_eps",
    "event_positive_eps_liq_high",
)
KEEP_EVENT = (
    "event_afterclose_positive_eps",
    "event_ta_up_positive_eps",
    "event_large_surprise_positive_eps",
    "surprise_xs_afterclose_ta_up",
    "event_ac_peps_taup",
)


def _by_id(pack: dict) -> dict:
    return {s["basket_id"]: s for s in pack["sleeves"]}


def test_reconstitution_evidence_apply_false_both_options() -> None:
    from research.combo_basket_catalog import (
        HUMAN_RECONSTITUTION_PENDING,
        KEEP_BOTH_SLEEVES_JOB,
        reconstitution_evidence_builder,
    )
    from research.eval_flags import RECONSTITUTION_APPLY
    from research.reconstitution_evidence import (
        COMPARISON_METRIC_KEYS,
        DEFAULT_RECOMMENDED_CHOICE,
        reconstitution_evidence_pack,
    )

    assert RECONSTITUTION_APPLY is False
    pack = reconstitution_evidence_pack()
    built = reconstitution_evidence_builder()
    assert built["version"] == pack["version"]
    assert pack["apply"] is False
    assert pack["go"] is False
    assert pack["not_a_pass"] is True
    assert pack["do_not_auto_choose"] is True
    assert pack["human_choice_required"] is True
    assert pack["recommended_choice_is_not_apply"] is True
    assert pack["do_not_invent_sharpe"] is True
    assert pack["economics_clearly_better"] is False
    assert pack["recommended_choice"] == DEFAULT_RECOMMENDED_CHOICE
    assert pack["recommended_choice"] == "drop_children_keep_parents"
    assert pack["evidence_status"] == "local_schema_only"
    assert pack["keep_sleeves_job"] == KEEP_BOTH_SLEEVES_JOB
    assert pack["human_pending"] == list(HUMAN_RECONSTITUTION_PENDING)
    assert pack["options"] == [
        "drop_parents_keep_children",
        "drop_children_keep_parents",
    ]
    for key in COMPARISON_METRIC_KEYS:
        assert key in pack["metric_keys"]
    by_id = _by_id(pack)
    assert set(by_id) == {"basket_theme_fund", "basket_event_fund"}
    for bid, sleeve in by_id.items():
        assert sleeve["apply"] is False
        assert sleeve["go"] is False
        assert "drop_parents_keep_children" in sleeve
        assert "drop_children_keep_parents" in sleeve
        assert sleeve["drop_parents_keep_children"]["apply"] is False
        assert sleeve["drop_children_keep_parents"]["apply"] is False
        for key in COMPARISON_METRIC_KEYS:
            assert key in sleeve["drop_parents_keep_children"]["metrics"]
            assert key in sleeve["drop_children_keep_parents"]["metrics"]
        assert sleeve["drop_parents_keep_children"]["metrics"]["net_sharpe"] is None
        assert sleeve["drop_children_keep_parents"]["metrics"]["net_sharpe"] is None
        assert sleeve["current"]["metrics"]["net_sharpe"] is None
        assert bid in ("basket_theme_fund", "basket_event_fund")
    assert RECONSTITUTION_APPLY is False


def test_theme_fund_parent_vs_child_cuts() -> None:
    from research.reconstitution_evidence import reconstitution_evidence_pack

    fund = _by_id(reconstitution_evidence_pack())["basket_theme_fund"]
    assert tuple(fund["current"]["members"]) == KEEP_FUND
    assert fund["current"]["sleeve_breadth"] == 5
    drop_p = fund["drop_parents_keep_children"]
    drop_c = fund["drop_children_keep_parents"]
    assert drop_p["dropped"] == ["event_ta_up_positive_eps"]
    assert "event_ta_up_positive_eps" not in drop_p["members"]
    assert "event_ac_peps_taup" in drop_p["members"]
    assert drop_c["dropped"] == ["event_ac_peps_taup"]
    assert "event_ac_peps_taup" not in drop_c["members"]
    assert "event_ta_up_positive_eps" in drop_c["members"]
    assert drop_p["sleeve_breadth"] == 4
    assert drop_c["sleeve_breadth"] == 4


def test_event_fund_three_parents_vs_child_cuts() -> None:
    from research.reconstitution_evidence import reconstitution_evidence_pack

    evf = _by_id(reconstitution_evidence_pack())["basket_event_fund"]
    assert tuple(evf["current"]["members"]) == KEEP_EVENT
    assert evf["current"]["sleeve_breadth"] == 5
    drop_p = evf["drop_parents_keep_children"]
    drop_c = evf["drop_children_keep_parents"]
    assert set(drop_p["dropped"]) == {
        "event_afterclose_positive_eps",
        "event_ta_up_positive_eps",
        "surprise_xs_afterclose_ta_up",
    }
    assert drop_p["sleeve_breadth"] == 2
    assert "event_ac_peps_taup" in drop_p["members"]
    assert drop_c["dropped"] == ["event_ac_peps_taup"]
    assert drop_c["sleeve_breadth"] == 4
    assert "event_ac_peps_taup" not in drop_c["members"]
    assert evf["economics_clearly_better"] is False


def test_occupancy_maps_do_not_invent_sharpe() -> None:
    from research.reconstitution_evidence import reconstitution_evidence_pack

    pack = reconstitution_evidence_pack(
        {
            "mid_n_explore": {"event_ta_up_positive_eps": 0.4},
            "liq_large": {"event_ta_up_positive_eps": 0.41},
        }
    )
    assert pack["apply"] is False
    assert pack["evidence_status"] == "local_schema_only"
    fund = _by_id(pack)["basket_theme_fund"]
    current = fund["current"]["metrics"]
    assert current["net_sharpe"] is None
    assert current["net_return"] is None
    assert current["max_dd"] is None
    assert current["occupancy"] == 0.4
    assert current["mid_n_explore"] == 0.4
    assert current["liq_large"] == 0.41
    assert pack["recommended_choice"] == "drop_children_keep_parents"
    assert pack["economics_clearly_better"] is False


def test_missing_cells_root_is_r2_missing(tmp_path) -> None:
    from research.reconstitution_evidence import reconstitution_evidence_pack

    pack = reconstitution_evidence_pack(cells_root=tmp_path)
    assert pack["evidence_status"] == "r2_missing"
    assert pack["apply"] is False
    assert pack["go"] is False
    assert pack["recommended_choice"] == "drop_children_keep_parents"
    fund = _by_id(pack)["basket_theme_fund"]
    assert fund["drop_parents_keep_children"]["metrics"]["net_sharpe"] is None
    assert fund["drop_children_keep_parents"]["metrics"]["net_sharpe"] is None


def test_keep_24df_members_unchanged_after_pack() -> None:
    from research.combo_basket_catalog import mechanical_basket_defs
    from research.reconstitution_evidence import reconstitution_evidence_pack

    before = {
        d["basket_id"]: list(d["members"])
        for d in mechanical_basket_defs()
        if d["basket_id"] in {"basket_theme_fund", "basket_event_fund"}
    }
    reconstitution_evidence_pack()
    after = {
        d["basket_id"]: list(d["members"])
        for d in mechanical_basket_defs()
        if d["basket_id"] in {"basket_theme_fund", "basket_event_fund"}
    }
    assert before == after
    assert before["basket_theme_fund"] == list(KEEP_FUND)
    assert before["basket_event_fund"] == list(KEEP_EVENT)


def test_write_evidence_pack_dry_run_only(tmp_path) -> None:
    from research.eval_flags import RECONSTITUTION_APPLY
    from research.reconstitution_evidence import write_reconstitution_evidence_pack

    out = write_reconstitution_evidence_pack(
        wave="test24ev",
        root=tmp_path,
        dry_run=True,
        put_r2=False,
        staging_dir=tmp_path / "stage",
    )
    assert out["apply"] is False
    assert out["go"] is False
    assert out["dry_run"] is True
    assert out["put_r2"] is False
    assert out["pack"]["apply"] is False
    assert (tmp_path / "eval-reconstitution-evidence-test24ev.json").is_file()
    raw = json.loads(
        (tmp_path / "eval-reconstitution-evidence-test24ev.json").read_text(
            encoding="utf-8"
        )
    )
    assert raw["apply"] is False
    assert "drop_parents_keep_children" in raw["sleeves"][0]
    assert "drop_children_keep_parents" in raw["sleeves"][0]
    assert out["put"] is not None
    assert out["put"]["status"] == "dry_run"
    assert RECONSTITUTION_APPLY is False
    with pytest.raises(ValueError, match="never live-puts"):
        write_reconstitution_evidence_pack(
            wave="test24ev",
            root=tmp_path,
            dry_run=False,
            put_r2=True,
        )


def test_write_evidence_pack_dry_run_does_not_call_worker(
    tmp_path, monkeypatch
) -> None:
    def _boom(*_a, **_k):
        raise AssertionError("dry_run must not Worker-put")

    monkeypatch.setattr(
        "research.r2_io.put_children_then_manifest_via_worker",
        _boom,
    )
    from research.reconstitution_evidence import write_reconstitution_evidence_pack

    out = write_reconstitution_evidence_pack(
        wave="test24ev",
        root=tmp_path,
        dry_run=True,
        put_r2=False,
        staging_dir=tmp_path / "stage",
    )
    assert out["put"] is not None
    assert out["put"]["status"] == "dry_run"
    assert out["dry_run"] is True
    assert out["put_r2"] is False
    assert out["go"] is False
    assert out["apply"] is False


def test_injected_cells_fill_sharpe_without_apply() -> None:
    from research.reconstitution_evidence import reconstitution_evidence_pack

    dates = ["d0", "d1", "d2", "d3"]
    net = [0.0, 0.01, -0.004, 0.02]
    cells = []
    for lid in KEEP_FUND:
        cells.append(
            {
                "logic_id": lid,
                "window_id": "w0",
                "dates": dates,
                "net_daily": list(net),
                "occupancy": 0.3,
                "daily_path_complete": True,
            }
        )
    pack = reconstitution_evidence_pack(
        cells_by_track={"mid_n_explore": cells, "liq_large": []}
    )
    assert pack["evidence_status"] == "cells_present"
    assert pack["apply"] is False
    fund = _by_id(pack)["basket_theme_fund"]
    mid = fund["drop_children_keep_parents"]["by_track"]["mid_n_explore"]
    assert mid["net_sharpe"] is not None
    assert isinstance(mid["net_sharpe"], float)
    assert pack["recommended_choice"] == "drop_children_keep_parents"
    assert pack["economics_clearly_better"] is False
