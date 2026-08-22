"""CF Worker POST /v1/propose-thesis. Does not write YAML. Does not GO.

Remote proposals SoT is the Worker route. Local
``research.offline.factory_propose.propose_profit_hypotheses`` stays
offline-only. Does not import factory / class_hyp_eval / bar_eval.
"""

from __future__ import annotations

import json
from typing import Any, Callable, Mapping, Sequence
from uuid import uuid4

from research.cf_mass_eval_job import (
    DEFAULT_WORKER_URL,
    CfMassEvalError,
    resolve_research_run_token,
)
from research.complete21 import COMPLETE_21_DATASET_SET
from research.unique_logic.constants import (
    PROPOSE_ALLOWED_GATES,
    SPARSE_GATE_COMBOS,
)

# Copied from factory_propose._is_window_tweak_only (do not import factory).
_TWEAK_WORDS = ("window", "hold_days only", "mom only", "frac only")

PROPOSE_ALLOWED_DATASETS: frozenset[str] = frozenset(
    {
        "equities_bars_daily",
        "fins_summary",
        "markets_calendar",
        "markets_margin_interest",
        "markets_short_ratio",
        "jsda_tokyo_repo_rates",
    }
)
if not PROPOSE_ALLOWED_DATASETS <= COMPLETE_21_DATASET_SET:
    raise RuntimeError("propose datasets must be a subset of COMPLETE 21")

_PROMPT_DIRECTION_ECHO: tuple[str, ...] = (
    "liquidity × fundamentals",
    "liquidity x fundamentals",
    "margin × price",
    "margin x price",
    "disclosure × funding",
    "disclosure x funding",
)

# LLM English titles sometimes invert gate polarity (sales_down → "Rising Sales").
# Review follows GATES, not the title; reject the row rather than adopt inverted copy.
_GATE_TITLE_CONTRA: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("sales_down", ("rising sales", "sales up", "sales growth", "high sales", "sales increase")),
    ("np_negative", ("positive np", "positive profit", "rising profit", "profit up")),
    ("price_down", ("price up", "rising price", "increase in price", "price increase")),
    ("ta_down", ("ta up", "rising ta")),
    ("ta_up", ("ta down", "falling ta")),
    ("eq_ar_falling", (
        "rising eqar",
        "eqar rising",
        "eq ar rising",
        "high eqar",
        "high equity",
        "rising equity",
        "equity risk premium is rising",
        "rising equity risk",
    )),
    ("eq_ar_rising", ("falling eqar", "eqar falling", "eq ar falling")),
    ("eq_ar_low", ("high eqar", "eqar high", "eq ar high")),
    ("eq_ar_high", ("low eqar", "eqar low", "eq ar low")),
    ("tight_funding", ("easy funding", "funding easing", "eased funding")),
    ("easy_funding", ("tight funding", "funding tight")),
    ("eps_down", ("eps up", "rising eps")),
    ("eps_up", ("eps down", "falling eps")),
    ("margin_down", ("margin up", "rising margin")),
    ("margin_up", ("margin down", "falling margin")),
    # nky_vol_high_skip occupancy is skip-when-high OFF, not "vol is high".
    (
        "nky_vol_high_skip",
        ("volatility is high", "vol is high", "high volatility", "nky vol high"),
    ),
    ("crowded_margin", ("uncrowded",)),
    ("uncrowded_margin", ("is crowded", "margin is crowded")),
    ("cheap_iv", ("rich iv", "iv is rich", "expensive iv")),
    ("rich_iv", ("cheap iv", "iv is cheap")),
    ("overnight_easing", ("tightening",)),
    ("overnight_tightening", ("easing", "easy funding")),
    ("repo_3m_down", ("high repo", "repo rate is high", "rising repo", "repo up")),
)

# Occupancy is the gate predicate (EqAR change, repo-down). English slang
# ("risk appetite", "repo is low") is not occupancy — reject rather than adopt.
_GATE_OCCUPANCY_LABEL: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("eq_ar_falling", ("risk appetite", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_rising", ("risk appetite", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_high", ("risk appetite", "risk premia", "risk premium", "risk arbitrage")),
    ("eq_ar_low", ("risk appetite", "risk premia", "risk premium", "risk arbitrage")),
    ("repo_3m_down", ("repo rates are low", "low repo", "repo is low")),
    ("ta_up", ("technical analysis", "technical signal", "ta signals")),
    ("ta_down", ("technical analysis", "technical signal", "ta signals")),
    ("overnight_p10", ("at 10%", "funding at 10", "10 percent", "10% predicts")),
)

PROPOSE_MAX_AND_GATES: int = 3
PROPOSE_WHY_AVOID_LIMIT: int = 24

PROPOSE_CONTRADICTORY_GATE_PAIRS: tuple[frozenset[str], ...] = (
    frozenset({"easy_funding", "tight_funding"}),
    frozenset({"crowded_margin", "uncrowded_margin"}),
    frozenset({"eq_ar_high", "eq_ar_low"}),
    frozenset({"eq_ar_rising", "eq_ar_falling"}),
    frozenset({"cheap_iv", "rich_iv"}),
    frozenset({"ta_up", "ta_down"}),
    frozenset({"overnight_easing", "overnight_tightening"}),
    frozenset({"margin_up", "margin_down"}),
    frozenset({"eps_up", "eps_down"}),
)

STUB_PROPOSAL_TEMPLATES: tuple[dict[str, Any], ...] = (
    {
        "thesis": (
            "STUB (not catalog): liquidity × fundamentals — high-ADV names "
            "with conservative EqAR/TA change after disclosure."
        ),
        "signal_definition": (
            "AND(liq_high, EqAR-or-TA-change) on the event window; skip "
            "missing ADV/EqAR/TA (no invent)."
        ),
        "position_rule": (
            "Event-hold original surprise sign when both gates are PIT-true; "
            "otherwise flat."
        ),
        "datasets": ["equities_bars_daily", "fins_summary", "markets_calendar"],
        "gates": ["liq_high", "eq_ar_high"],
        "why_different_from": ["ungated PEAD", "always-on CS EqAR sticky"],
    },
    {
        "thesis": (
            "STUB (not catalog): margin × price disagreement — fade names "
            "where margin is crowded while price still rises."
        ),
        "signal_definition": (
            "AND(crowded_margin, price_up) occupancy; skip missing margin "
            "PIT prints (no ffill)."
        ),
        "position_rule": "CS fade (invert mom) while both gates hold; otherwise flat.",
        "datasets": [
            "equities_bars_daily",
            "markets_margin_interest",
            "markets_calendar",
        ],
        "gates": ["crowded_margin"],
        "why_different_from": ["ungated CS mom", "margin-only crowd fade"],
    },
    {
        "thesis": (
            "STUB (not catalog): disclosure × funding — PEAD only when "
            "overnight repo eased into the print cluster."
        ),
        "signal_definition": (
            "AND(afterclose-or-cluster, overnight_easing) on disclosure; "
            "skip missing repo (no invent)."
        ),
        "position_rule": (
            "Event-hold original surprise sign when funding eased; otherwise flat."
        ),
        "datasets": [
            "equities_bars_daily",
            "fins_summary",
            "jsda_tokyo_repo_rates",
            "markets_calendar",
        ],
        "gates": ["afterclose", "overnight_easing"],
        "why_different_from": ["ungated PEAD", "overnight-level CS sticky"],
    },
)


def review_proposal_row(proposal: Mapping[str, Any]) -> dict[str, Any]:
    """Local review of an LLM row. Never injects. Never GO."""
    reasons: list[str] = []
    if "logic_id" in proposal:
        reasons.append("logic_id_forbidden")
    if reject_window_tweak(proposal):
        reasons.append("window_tweak_only_forbidden")
    datasets = [
        str(x)
        for x in (proposal.get("datasets") or proposal.get("datasets_used") or [])
        if str(x).strip()
    ]
    kept_ds = [d for d in datasets if d in PROPOSE_ALLOWED_DATASETS]
    if not kept_ds:
        reasons.append("datasets_not_complete21_sidecars")
    invented_ds = [d for d in datasets if d not in PROPOSE_ALLOWED_DATASETS]
    if invented_ds:
        reasons.append("invented_datasets")
    gates = [str(x) for x in (proposal.get("gates") or []) if str(x).strip()]
    kept_g = [g for g in gates if g in PROPOSE_ALLOWED_GATES]
    if not kept_g:
        reasons.append("gates_empty_or_not_economic")
    invented_g = [g for g in gates if g not in PROPOSE_ALLOWED_GATES]
    if invented_g:
        reasons.append("invented_or_calendar_gates")
    thesis = str(proposal.get("thesis") or "")
    if kept_g and not thesis.startswith("STUB"):
        from research.unique_logic.catalog import yaml_combo_rows

        catalog_sets = {
            frozenset(
                str(x)
                for x in ((row.get("params") or {}).get("gates") or [])
                if str(x).strip()
            )
            for row in yaml_combo_rows()
        }
        if frozenset(kept_g) in catalog_sets:
            reasons.append("gate_set_already_catalog")
        kept_set = frozenset(kept_g)
        if any(pair <= kept_set for pair in PROPOSE_CONTRADICTORY_GATE_PAIRS):
            reasons.append("contradictory_gates")
        if len(kept_g) < 2:
            reasons.append("gates_not_a_cross")
        if len(kept_g) > PROPOSE_MAX_AND_GATES:
            reasons.append("and_cross_too_wide")
        blob = thesis.lower().replace("×", "x")
        if any(echo.replace("×", "x") in blob for echo in _PROMPT_DIRECTION_ECHO):
            reasons.append("prompt_direction_echo")
        if (" × " in thesis or " x " in blob) and not any(
            w in blob
            for w in (
                "when ",
                " while ",
                "after ",
                "pead",
                "skip ",
                " pit",
                "hold ",
                "fade",
                " names",
            )
        ):
            reasons.append("title_not_occupancy")
        polar_blob = blob.replace("_", " ").replace("-", " ")
        for gate, forbidden in _GATE_TITLE_CONTRA:
            if gate not in kept_set:
                continue
            if any(w in polar_blob for w in forbidden):
                reasons.append("title_gate_polarity_mismatch")
                break
        for gate, labels in _GATE_OCCUPANCY_LABEL:
            if gate not in kept_set:
                continue
            if not any(w in polar_blob for w in labels):
                continue
            if gate.startswith("eq_ar") and any(
                t in polar_blob for t in ("eqar", "eq ar", "equity to asset")
            ):
                continue
            if gate.startswith("ta_") and "total assets" in polar_blob:
                continue
            if gate == "overnight_p10" and any(
                t in polar_blob
                for t in ("easiest", "percentile", "decile", "p10")
            ):
                continue
            reasons.append("occupancy_label_only")
            break
        for combo, _reason in SPARSE_GATE_COMBOS:
            if combo <= kept_set:
                reasons.append("sparse_gate_combo")
                break
    ok = not reasons
    return {
        "ok": ok,
        "reasons": reasons,
        "datasets": kept_ds,
        "gates": kept_g,
        "auto_inject": False,
        "go": False,
        "not_injected": True,
        "not_a_pass": True,
    }


def catalog_gate_set_avoid(*, limit: int = PROPOSE_WHY_AVOID_LIMIT) -> list[str]:
    """Existing countable AND-sets for LLM why_avoid.

    Newest YAML first. Reserve half the cap for 3-gates and half for
    2-gates so a 3-gate-only fill cannot hide recent 2-AND clones.
    Calendar/weekday permutations are not clone seeds. Not a scorecard.
    """
    from research.unique_logic.catalog import catalog_dir, yaml_combo_rows
    from research.unique_logic.constants import PROPOSE_CALENDAR_GATES
    from research.unique_logic.worker_bodies import countable_thesis_ids

    countable = countable_thesis_ids()
    cdir = catalog_dir()
    twos: list[tuple[float, str]] = []
    threes: list[tuple[float, str]] = []
    have: set[str] = set()
    for row in yaml_combo_rows():
        lid = str(row.get("logic_id") or "")
        if lid and lid not in countable:
            continue
        gates = sorted(
            str(x)
            for x in ((row.get("params") or {}).get("gates") or [])
            if str(x).strip()
        )
        if not (2 <= len(gates) <= PROPOSE_MAX_AND_GATES):
            continue
        if PROPOSE_CALENDAR_GATES.intersection(gates):
            continue
        token = "+".join(gates)
        if token in have:
            continue
        have.add(token)
        yp = cdir / f"{lid}.yaml"
        mtime = yp.stat().st_mtime if yp.is_file() else 0.0
        if len(gates) == 2:
            twos.append((mtime, token))
        else:
            threes.append((mtime, token))
    twos.sort(reverse=True)
    threes.sort(reverse=True)
    lim = max(1, int(limit))
    n3 = min(len(threes), max(1, lim // 2))
    n2 = min(len(twos), lim - n3)
    if n2 < min(len(twos), lim // 2):
        n2 = min(len(twos), lim // 2)
        n3 = min(len(threes), lim - n2)
    return [t for _, t in threes[:n3]] + [t for _, t in twos[:n2]]


def sparse_gate_set_avoid() -> list[str]:
    """Recorded empty AND-sets. Prepended to why_avoid. Does not GO."""
    from research.unique_logic.constants import (
        PROPOSE_CALENDAR_GATES,
        SPARSE_GATE_COMBOS,
    )

    out: list[str] = []
    have: set[str] = set()
    for combo, _reason in SPARSE_GATE_COMBOS:
        if len(combo) < 2:
            continue
        if combo & PROPOSE_CALENDAR_GATES:
            continue
        token = "+".join(sorted(combo))
        if token in have:
            continue
        have.add(token)
        out.append(token)
    return out


def reject_window_tweak(proposal: Mapping[str, Any]) -> bool:
    """True when proposal only mutates hold/mom/window without a new thesis."""
    thesis = str(proposal.get("thesis") or "").strip()
    signal = str(
        proposal.get("signal_definition") or proposal.get("signal") or ""
    ).strip()
    position = str(
        proposal.get("position_rule") or proposal.get("position") or ""
    ).strip()
    if not thesis or not signal or not position:
        return True
    blob = f"{thesis} {signal}".lower()
    if any(w in blob for w in _TWEAK_WORDS) and "factor" not in blob:
        if not proposal.get("datasets") and not proposal.get("datasets_used"):
            return True
    return False


def stub_propose_thesis_result(
    *,
    n: int = 3,
    why_avoid: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Test fixture for the historical unbound-AI payload shape. Not live.

    Live Worker ``/v1/propose-thesis`` returns ``ok:false`` ``llm_failed``.
    ``invoke_cf_propose_thesis`` never calls this helper.
    """
    want = max(1, min(3, int(n)))
    avoid = {str(x) for x in (why_avoid or ())}
    proposals: list[dict[str, Any]] = []
    for tpl in STUB_PROPOSAL_TEMPLATES:
        if len(proposals) >= want:
            break
        proposals.append(
            {
                "thesis": tpl["thesis"],
                "signal_definition": tpl["signal_definition"],
                "position_rule": tpl["position_rule"],
                "datasets": list(tpl["datasets"]),
                "gates": list(tpl["gates"]),
                "why_different_from": [
                    x for x in tpl["why_different_from"] if x not in avoid
                ],
                "not_injected": True,
                "status": "stub_not_catalog",
            }
        )
    return {
        "ok": True,
        "proposals": proposals,
        "auto_inject": False,
        "go": False,
        "not_a_pass": True,
        "catalog_written": False,
        "ids_injected": False,
    }


def _attach_reviews(
    out: dict[str, Any],
    *,
    write_sidecar: bool = False,
    job_id: str | None = None,
) -> dict[str, Any]:
    """Stamp review_proposal_row onto a Worker payload. Never injects."""
    rows = [p for p in (out.get("proposals") or []) if isinstance(p, Mapping)]
    reviews: list[dict[str, Any]] = []
    n_ok = 0
    for p in rows:
        rev = review_proposal_row(p)
        reviews.append(rev)
        stub = str(p.get("status") or "").startswith("stub") or str(
            p.get("thesis") or ""
        ).startswith("STUB")
        if rev["ok"] and not stub:
            n_ok += 1
    out["reviews"] = reviews
    out["n_adoptable"] = n_ok
    out["auto_inject"] = False
    out["catalog_written"] = False
    out["ids_injected"] = False
    out["go"] = False
    out["not_a_pass"] = True
    if write_sidecar and job_id:
        from research.cf_mass_eval_stage import RESEARCH_ARTIFACT_BUCKET
        from research.r2_io import default_r2_put

        key = f"research/eval/job={job_id}/review.json"
        default_r2_put(
            RESEARCH_ARTIFACT_BUCKET,
            key,
            json.dumps(
                {
                    "job_id": job_id,
                    "n_adoptable": n_ok,
                    "adopted": [],
                    "reviews": reviews,
                    "auto_inject": False,
                    "go": False,
                    "catalog_written": False,
                    "not_a_pass": True,
                },
                default=str,
            ).encode("utf-8"),
        )
        out["review_r2_key"] = key
    return out


def invoke_cf_propose_thesis(
    *,
    n: int = 3,
    why_avoid: Sequence[str] | None = None,
    write_artifacts: bool = False,
    job_id: str | None = None,
    worker_url: str = DEFAULT_WORKER_URL,
    timeout: int = 120,
    http_post: Callable[..., Any] | None = None,
    proposal: Mapping[str, Any] | None = None,
    proposals: Sequence[Mapping[str, Any]] | None = None,
    retry_on_clone: bool = True,
) -> dict[str, Any]:
    """POST /v1/propose-thesis. Does not write catalog YAML or inject IDs."""
    if proposal is not None and reject_window_tweak(proposal):
        return {
            "ok": False,
            "error": "window_tweak_only_forbidden",
            "auto_inject": False,
            "go": False,
            "not_a_pass": True,
        }
    for raw in proposals or ():
        if reject_window_tweak(raw):
            return {
                "ok": False,
                "error": "window_tweak_only_forbidden",
                "auto_inject": False,
                "go": False,
                "not_a_pass": True,
            }

    url = worker_url.rstrip("/") + "/v1/propose-thesis"
    auth_tok = resolve_research_run_token() or ""
    avoid: list[str] = []
    seen_avoid: set[str] = set()
    for item in (
        list(why_avoid or ()) + sparse_gate_set_avoid() + catalog_gate_set_avoid()
    ):
        token = str(item).strip()
        if not token or token in seen_avoid:
            continue
        seen_avoid.add(token)
        avoid.append(token)
        if len(avoid) >= PROPOSE_WHY_AVOID_LIMIT:
            break
    body: dict[str, Any] = {
        "n": max(1, min(3, int(n))),
        "why_avoid": avoid,
        "write_artifacts": bool(write_artifacts),
        "auto_inject": False,
        "go": False,
    }
    if job_id:
        body["job_id"] = str(job_id)
    elif write_artifacts:
        body["job_id"] = f"propose-{uuid4().hex[:10]}"
    if proposal is not None:
        body["thesis"] = proposal.get("thesis")
        body["signal_definition"] = proposal.get("signal_definition") or proposal.get(
            "signal"
        )
        body["position_rule"] = proposal.get("position_rule") or proposal.get(
            "position"
        )
        if proposal.get("datasets") or proposal.get("datasets_used"):
            body["datasets"] = list(
                proposal.get("datasets") or proposal.get("datasets_used") or []
            )
    if proposals is not None:
        body["proposals"] = [dict(p) for p in proposals]
    payload = json.dumps(body, default=str).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "quant-platform-cf-propose-thesis/1.0",
    }
    if auth_tok:
        headers["Authorization"] = f"Bearer {auth_tok}"
        headers["X-Research-Run-Token"] = auth_tok
        headers["X-Mass-Eval-Token"] = auth_tok
        headers["X-Ingestion-Token"] = auth_tok

    if http_post is not None:
        raw_resp = http_post(url=url, body=payload, headers=headers)
        if isinstance(raw_resp, Mapping):
            parsed: dict[str, Any] = dict(raw_resp)
        else:
            text = raw_resp if isinstance(raw_resp, str) else raw_resp.decode("utf-8")
            loaded = json.loads(text)
            if not isinstance(loaded, dict):
                raise CfMassEvalError("propose-thesis response not an object")
            parsed = loaded
        reviewed = _attach_reviews(
            parsed,
            write_sidecar=False,
            job_id=str(body.get("job_id") or "") or None,
        )
    else:
        import urllib.error
        import urllib.request

        req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8")[:4000]
            except Exception:
                detail = str(exc)
            try:
                failed = json.loads(detail)
            except json.JSONDecodeError:
                failed = None
            if (
                isinstance(failed, dict)
                and failed.get("error") == "llm_failed"
            ):
                raw = json.dumps(failed)
            else:
                raise CfMassEvalError(
                    f"propose-thesis HTTP {exc.code}: {detail}"
                ) from exc
        except urllib.error.URLError as exc:
            raise CfMassEvalError(f"propose-thesis network error: {exc}") from exc
        try:
            out = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CfMassEvalError(f"propose-thesis non-json: {raw[:500]}") from exc
        if not isinstance(out, dict):
            raise CfMassEvalError("propose-thesis response not an object")
        reviewed = _attach_reviews(
            out,
            write_sidecar=bool(write_artifacts),
            job_id=str(body.get("job_id") or "") or None,
        )
    if (
        retry_on_clone
        and reviewed.get("workers_ai_used")
        and int(reviewed.get("n_adoptable") or 0) == 0
    ):
        extra = []
        seen_extra: set[str] = set()
        # Clone/sparse: avoid those gate sets. Polarity/occupancy-label:
        # retry once without avoiding the (possibly unique) AND.
        avoid_reasons = {
            "gate_set_already_catalog",
            "sparse_gate_combo",
        }
        for prop, rev in zip(
            reviewed.get("proposals") or [],
            reviewed.get("reviews") or [],
        ):
            if not isinstance(prop, Mapping) or not isinstance(rev, Mapping):
                continue
            reasons = set(str(x) for x in (rev.get("reasons") or []))
            if not (reasons & avoid_reasons):
                continue
            gates = [str(x) for x in (prop.get("gates") or []) if str(x).strip()]
            if not gates:
                continue
            token = "+".join(sorted(gates))
            if token in seen_extra:
                continue
            seen_extra.add(token)
            extra.append(token)
        jid = str(body.get("job_id") or "")
        return invoke_cf_propose_thesis(
            n=n,
            why_avoid=extra + list(avoid),
            write_artifacts=write_artifacts,
            job_id=f"{jid}-retry" if jid else None,
            worker_url=worker_url,
            timeout=timeout,
            http_post=http_post,
            retry_on_clone=False,
        )
    return reviewed


__all__ = [
    "PROPOSE_ALLOWED_DATASETS",
    "PROPOSE_WHY_AVOID_LIMIT",
    "STUB_PROPOSAL_TEMPLATES",
    "catalog_gate_set_avoid",
    "sparse_gate_set_avoid",
    "invoke_cf_propose_thesis",
    "reject_window_tweak",
    "review_proposal_row",
    "stub_propose_thesis_result",
]
