"""W106 / w0820c — family append is recognition, not promotion."""

from __future__ import annotations

from research.mass_strategy_factory import (
    CONNECTED_TO_MASS,
    CONNECTED_TO_READY,
    FAMILY_DEFINITIONS,
    FROZEN_DEFAULT_PATH,
    LOGIC_TEMPLATES,
    MASS_RESEARCH,
    OPERATIONAL_GO,
    READY_DECLARED,
    RESEARCH_FAMILY_APPEND_ID,
    RESEARCH_FAMILY_APPEND_LOGIC_IDS,
    RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE,
    RESEARCH_FAMILY_REGISTER_ID,
    RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS,
    RESEARCH_UNIQUE_FAMILY_IDS,
    RESEARCH_UNIQUE_LOGIC_IDS,
    MassFactoryConfig,
    generate_strategy_batch,
    propose_profit_hypotheses,
    research_family_append_document,
    research_family_register_document,
    validate_strategy_at_gen,
)

from research.unique_logic import w106


def test_family_append_is_recognition_not_pass():
    doc = research_family_append_document()
    assert doc["append_id"] == RESEARCH_FAMILY_APPEND_ID
    assert doc["register_id"] == RESEARCH_FAMILY_REGISTER_ID
    assert doc["registration"] == "recognition"
    assert doc["registration_is_not_a_pass"] is True
    assert RESEARCH_FAMILY_REGISTRATION_IS_NOT_A_PASS is True
    assert doc["registration_is_not_promotion"] is True
    assert doc["auto_research_candidate"] is False
    assert RESEARCH_FAMILY_AUTO_RESEARCH_CANDIDATE is False
    assert doc["generation_enabled"] is False
    assert doc["promote_as_main"] is False
    assert doc["go"] is False
    assert doc["this_wave_only"] is True
    assert doc["did_not_kill_funding_surprise"] is True
    assert doc["sign_flip_is_not_a_kill"] is True
    assert doc["mass_research"] == "NO-GO"
    assert MASS_RESEARCH == "NO-GO"
    assert READY_DECLARED is False
    assert OPERATIONAL_GO is False
    assert CONNECTED_TO_MASS is False
    assert CONNECTED_TO_READY is False
    assert set(doc["appended_logic_ids"]) == set(RESEARCH_FAMILY_APPEND_LOGIC_IDS)
    assert set(RESEARCH_FAMILY_APPEND_LOGIC_IDS) <= set(RESEARCH_UNIQUE_LOGIC_IDS)
    assert "treat family append as a pass" in doc["must_not"]
    assert any("kill funding" in x for x in doc["must_not"])


def test_append_logics_registered_not_generated():
    lids = [s["logic_id"] for s in w106.NEW_LS_VARIANTS]
    assert set(lids) <= set(RESEARCH_UNIQUE_LOGIC_IDS)
    assert RESEARCH_FAMILY_APPEND_LOGIC_IDS <= RESEARCH_UNIQUE_LOGIC_IDS
    for lid in sorted(RESEARCH_FAMILY_APPEND_LOGIC_IDS):
        tpl = LOGIC_TEMPLATES[lid]
        assert tpl.generation_enabled is False
        assert tpl.family_id in FAMILY_DEFINITIONS
        assert FAMILY_DEFINITIONS[tpl.family_id].generation_enabled is False
        assert tpl.family_id in RESEARCH_UNIQUE_FAMILY_IDS
        ok, reason = validate_strategy_at_gen(
            tpl.family_id,
            dict(tpl.base_params),
            logic_id=lid,
        )
        assert ok is True, reason
        assert reason is None

    gen = generate_strategy_batch(seed=870816, n=100)
    gen_lids = {s["logic_id"] for s in gen["strategies_after_dedup"]}
    assert gen_lids.isdisjoint(RESEARCH_FAMILY_APPEND_LOGIC_IDS)
    assert gen_lids.isdisjoint(RESEARCH_UNIQUE_LOGIC_IDS)


def test_append_factory_period_net_not_unknown_and_not_a_pass():
    out = propose_profit_hypotheses(
        w106.proposals_for_factory(),
        evaluate=True,
        synthetic=True,
        config=MassFactoryConfig(seed=8908206, n=20),
    )
    assert out["n_accepted"] == 3
    assert out["n_rejected"] == 0
    for a in out["accepted"]:
        assert a["logic_id"] in RESEARCH_UNIQUE_LOGIC_IDS
        assert a.get("eval_mapped_to_catalog") in (None, False)
        assert a.get("research_family_recognition") is True
        assert a.get("research_candidate") is False
        assert a.get("promote_as_main") is False
        assert a.get("go") is False
        assert a.get("registration") == "recognition"
        assert a.get("registration_is_not_a_pass") is True

    screens = list(out.get("eval_screens") or [])
    assert len(screens) == 3
    for s in screens:
        reasons = [str(x) for x in (s.get("reject_reasons") or [])]
        blob = " ".join(reasons).lower()
        assert "unknown_family" not in blob
        assert s.get("promote_as_main") in (None, False)

    results = list(out.get("eval_results") or [])
    assert results
    n_ok_any = sum(int(r.get("n_periods_ok") or 0) for r in results)
    assert n_ok_any > 0
    for r in results:
        for prow in r.get("period_rows") or []:
            skip = str(prow.get("skip_reason") or "")
            assert not skip.startswith("unknown_family:")
            if prow.get("status") == "ok":
                assert prow.get("research_family_recognition") is True
                assert prow.get("registration_is_not_a_pass") is True
                assert prow.get("research_candidate") is False
                assert prow.get("go") is False


def test_family_append_does_not_retune_pins():
    assert len(FROZEN_DEFAULT_PATH) == 3
    by_id = {r["representative_id"]: r for r in FROZEN_DEFAULT_PATH}
    assert by_id["cross_section_hold_10"]["momentum_n"] == 5
    assert by_id["cross_section_hold_10_mom3"]["momentum_n"] == 3
    assert by_id["fundamentals_hold_10"]["momentum_n"] == 10
    assert by_id["cross_section_hold_10"]["stance"] == "KEEP"
    assert by_id["cross_section_hold_10_mom3"]["stance"] == "PROMOTE"
    assert by_id["fundamentals_hold_10"]["stance"] == "KEEP"


def test_overall_register_includes_append_but_is_still_not_a_pass():
    doc = research_family_register_document()
    assert set(RESEARCH_FAMILY_APPEND_LOGIC_IDS) <= set(doc["logic_ids"])
    assert doc["registration"] == "recognition"
    assert doc["generation_enabled"] is False
    assert doc["go"] is False
