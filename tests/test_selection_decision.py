import pytest
from selection.decision import SelectionDecision


def test_selection_decision_roundtrip():
    d = SelectionDecision(
        decision="PROMOTE",
        reason_codes=("perf_ok", "risk_ok"),
        subject_id="s1",
        evidence={"sharpe": 1.2},
    )
    assert SelectionDecision.from_dict(d.to_dict()).decision == "PROMOTE"


def test_reject_unknown_fields():
    with pytest.raises(ValueError):
        SelectionDecision.from_dict({
            "decision": "HOLD",
            "reason_codes": ["x"],
            "subject_id": "s",
            "evil": True,
        })
