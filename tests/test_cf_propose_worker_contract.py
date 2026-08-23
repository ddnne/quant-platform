"""Worker /v1/propose-thesis contract. Does not write catalog. Does not GO."""
from __future__ import annotations

from pathlib import Path

from research.unique_logic.constants import (
    COMBO_EVENT_GATES,
    PROPOSE_ALLOWED_GATES,
    PROPOSE_CALENDAR_GATES,
)

REPO = Path(__file__).resolve().parents[1]
WORKER_SRC = REPO / "platform" / "workers" / "research-mass-eval" / "src"
WORKER_INDEX = WORKER_SRC / "index.ts"
WORKER_PROPOSE = WORKER_SRC / "propose_thesis.ts"
WORKER_ALLOWED = WORKER_SRC / "propose_allowed.ts"
WRANGLER = REPO / "platform" / "workers" / "research-mass-eval" / "wrangler.toml"


def test_worker_index_contains_propose_thesis_route() -> None:
    src = (
        WORKER_INDEX.read_text(encoding="utf-8")
        + "\n"
        + WORKER_PROPOSE.read_text(encoding="utf-8")
        + "\n"
        + WORKER_ALLOWED.read_text(encoding="utf-8")
    )
    assert "/v1/propose-thesis" in src
    assert "llm_failed" in src
    assert "llama-3.3-70b-instruct-fp8-fast" in src
    assert "glm-4.7-flash" in src
    assert "signal_definition" in src
    assert "proposal_source: \"llm_failed\"" in src or "proposal_source: 'llm_failed'" in src or 'proposal_source: "llm_failed"' in src
    assert "auto_inject: false" in src
    assert "go: false" in src
    assert "not_a_pass: true" in src
    wr = WRANGLER.read_text(encoding="utf-8")
    assert 'binding = "AI"' in wr
    assert "[ai]" in wr
    assert "env.AI.run" in src
    assert "llm_not_catalog" in src
    assert "stubProposals" not in src
    assert "stub_propose_thesis_result" not in src
    live_propose = (
        REPO / "packages" / "product" / "research" / "cf_propose_thesis.py"
    ).read_text(encoding="utf-8")
    assert "stub_propose_thesis_result" not in live_propose
    assert "STUB_PROPOSAL_TEMPLATES" not in live_propose
    assert "titleOccupancyBad" in src
    assert "gateAndToken" in src
    assert "avoidTokens" in src
    propose_src = WORKER_PROPOSE.read_text(encoding="utf-8")
    assert "const PROPOSE_ALLOWED_GATES = [" not in propose_src
    assert "const PROPOSE_ALLOWED_DATASETS = [" not in propose_src
    assert "PROPOSE_ALLOWED_GATES.join" in propose_src
    assert "PROPOSE_PROMPT_PREFER_GATES.join" in propose_src
    assert "JSON.stringify(PROPOSE_PROMPT_GOOD)" in propose_src
    from research.unique_logic.catalog import combo_thesis_records
    from research.unique_logic.constants import SPARSE_GATE_COMBOS
    from research.unique_logic.propose_review_tables import (
        PROPOSE_CONTRADICTORY_GATE_PAIRS,
        PROPOSE_PROMPT_GOOD,
        PROPOSE_PROMPT_PREFER_GATES,
        propose_prompt_good,
    )

    assert set(PROPOSE_PROMPT_PREFER_GATES) <= set(PROPOSE_ALLOWED_GATES)
    good = propose_prompt_good()
    assert good["gates"] == PROPOSE_PROMPT_GOOD["gates"]
    catalog_sets = {
        frozenset(str(x) for x in (row.get("gates") or []) if str(x).strip())
        for row in combo_thesis_records()
    }
    assert frozenset(str(g) for g in good["gates"]) not in catalog_sets
    prefer = list(PROPOSE_PROMPT_PREFER_GATES)
    first2: list[str] | None = None
    for i, a in enumerate(prefer):
        for b in prefer[i + 1 :]:
            pair = frozenset({a, b})
            if pair in catalog_sets:
                continue
            if any(combo <= pair for combo, _reason in SPARSE_GATE_COMBOS):
                continue
            if any(contra <= pair for contra in PROPOSE_CONTRADICTORY_GATE_PAIRS):
                continue
            first2 = [a, b]
            break
        if first2 is not None:
            break
    if first2 is not None:
        assert list(good["gates"]) == first2
        assert len(good["gates"]) == 2
    else:
        assert len(good["gates"]) in (2, 3)
        assert frozenset(str(g) for g in good["gates"]) not in catalog_sets
    assert "markets_margin_interest" in src
    assert '"margin_interest"' not in src
    # Generated allowlists: scripts/sync_cf_new_thesis_ids.py --check is SoT.
    assert PROPOSE_CALENDAR_GATES <= COMBO_EVENT_GATES
    assert PROPOSE_CALENDAR_GATES.isdisjoint(PROPOSE_ALLOWED_GATES)
    assert "skip_monday" not in PROPOSE_ALLOWED_GATES
    assert "friday_only" not in PROPOSE_ALLOWED_GATES


