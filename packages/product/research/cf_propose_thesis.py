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
from research.unique_logic.propose_review_tables import (
    EXTRA_TITLE_GATES,
    GATE_OCCUPANCY_LABEL,
    GATE_TITLE_CONTRA,
    PROMPT_DIRECTION_ECHO,
    PROPOSE_CONTRADICTORY_GATE_PAIRS,
    PROPOSE_TWEAK_WORDS,
    TITLE_OCCUPANCY_META,
    occupancy_exception_tokens,
    occupancy_extra_families,
)

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

PROPOSE_MAX_AND_GATES: int = 3
# Combined payload sent to the Worker. Prefer-catalog 2-ANDs then 3-ANDs
# then prefer-subset SPARSE (parked prefer ANDs) take the cap first so the
# LLM does not re-emit those clones. Remaining SPARSE / newest catalog fill.
# 48 filled at 32 prefer 2-ANDs + 16 prefer-SPARSE; bump so the next park
# does not truncate catalog 2-AND clone magnets.
PROPOSE_WHY_AVOID_LIMIT: int = 64
CATALOG_GATE_SET_AVOID_LIMIT: int = 24


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
        from research.unique_logic.catalog import combo_thesis_records

        catalog_sets = {
            frozenset(str(x) for x in (row.get("gates") or []) if str(x).strip())
            for row in combo_thesis_records()
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
        if any(echo.replace("×", "x") in blob for echo in PROMPT_DIRECTION_ECHO):
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
        if any(p in polar_blob for p in TITLE_OCCUPANCY_META):
            reasons.append("occupancy_label_only")
        for gate, forbidden in GATE_TITLE_CONTRA:
            if gate not in kept_set:
                continue
            if any(w in polar_blob for w in forbidden):
                reasons.append("title_gate_polarity_mismatch")
                break
        if "occupancy_label_only" not in reasons:
            for gate, labels in GATE_OCCUPANCY_LABEL:
                if gate not in kept_set:
                    continue
                if not any(w in polar_blob for w in labels):
                    continue
                if any(t in polar_blob for t in occupancy_exception_tokens(gate)):
                    continue
                reasons.append("occupancy_label_only")
                break
        if "occupancy_label_only" not in reasons:
            for phrase, owners in occupancy_extra_families():
                if phrase in polar_blob and kept_set.isdisjoint(owners):
                    reasons.append("occupancy_label_only")
                    break
            else:
                for phrase, gate in EXTRA_TITLE_GATES:
                    if phrase in polar_blob and gate not in kept_set:
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


def catalog_prefer_and_avoid(*, n_gates: int, limit: int | None = None) -> list[str]:
    """Catalog ANDs whose gates are all prefer seeds. Clone magnet.

    Unique prefer pairs (GOOD) are not catalog, so they stay off this list.
    3-ANDs are newest-first and capped so 2-ANDs still fit. Not GO.
    """
    from research.unique_logic.catalog import catalog_dir, combo_thesis_records
    from research.unique_logic.constants import PROPOSE_CALENDAR_GATES
    from research.unique_logic.propose_review_tables import (
        PROPOSE_PROMPT_PREFER_GATES,
    )
    from research.unique_logic.worker_bodies import countable_thesis_ids

    if n_gates not in (2, 3):
        raise ValueError("n_gates must be 2 or 3")
    prefer = set(PROPOSE_PROMPT_PREFER_GATES)
    countable = countable_thesis_ids()
    cdir = catalog_dir()
    rows: list[tuple[float, str]] = []
    have: set[str] = set()
    for row in combo_thesis_records():
        lid = str(row.get("logic_id") or "")
        if lid and lid not in countable:
            continue
        gates = sorted(
            str(x) for x in (row.get("gates") or []) if str(x).strip()
        )
        if len(gates) != n_gates:
            continue
        if PROPOSE_CALENDAR_GATES.intersection(gates):
            continue
        if not set(gates) <= prefer:
            continue
        token = "+".join(gates)
        if token in have:
            continue
        have.add(token)
        yp = cdir / f"{lid}.yaml"
        mtime = yp.stat().st_mtime if yp.is_file() else 0.0
        rows.append((mtime, token))
    rows.sort(reverse=True)
    tokens = [t for _, t in rows]
    if limit is not None:
        tokens = tokens[: max(0, int(limit))]
    return tokens


def catalog_prefer_pair_avoid() -> list[str]:
    return catalog_prefer_and_avoid(n_gates=2)


def catalog_prefer_triple_avoid(*, limit: int = 12) -> list[str]:
    """Newest catalog prefer 3-ANDs. 24ao cloned eps×px×tight after 2-AND fill."""
    return catalog_prefer_and_avoid(n_gates=3, limit=limit)


def assemble_why_avoid(extra: Sequence[str] | None = None) -> list[str]:
    """Prefer 2-ANDs, prefer 3-ANDs, prefer-subset SPARSE, then remaining.

    Prefer-subset SPARSE is reserved so parked prefer ANDs are not truncated
    when catalog prefer pairs fill the cap. Does not GO.
    """
    extra_toks = [str(x).strip() for x in (extra or ()) if str(x).strip()]
    pairs = catalog_prefer_pair_avoid()
    triples = catalog_prefer_triple_avoid()
    prefer_sparse = sparse_prefer_subset_avoid()
    prefer_sparse_set = set(prefer_sparse)
    rest_sparse = [t for t in sparse_gate_set_avoid() if t not in prefer_sparse_set]
    rest_catalog = catalog_gate_set_avoid()

    out: list[str] = []
    seen: set[str] = set()

    def _push(items: Sequence[str], *, cap: int) -> None:
        for item in items:
            token = str(item).strip()
            if not token or token in seen:
                continue
            if len(out) >= cap:
                return
            seen.add(token)
            out.append(token)

    reserve_n = min(len(prefer_sparse), PROPOSE_WHY_AVOID_LIMIT)
    prefix_cap = max(0, PROPOSE_WHY_AVOID_LIMIT - reserve_n)
    _push(extra_toks + pairs + triples, cap=prefix_cap)
    _push(prefer_sparse, cap=PROPOSE_WHY_AVOID_LIMIT)
    _push(rest_sparse + rest_catalog, cap=PROPOSE_WHY_AVOID_LIMIT)
    return out


def catalog_gate_set_avoid(*, limit: int = CATALOG_GATE_SET_AVOID_LIMIT) -> list[str]:
    """Existing countable AND-sets for LLM why_avoid.

    Newest YAML first. Reserve half the cap for 3-gates and half for
    2-gates so a 3-gate-only fill cannot hide recent 2-AND clones.
    Calendar/weekday permutations are not clone seeds. Not a scorecard.
    """
    from research.unique_logic.catalog import catalog_dir, combo_thesis_records
    from research.unique_logic.constants import PROPOSE_CALENDAR_GATES
    from research.unique_logic.worker_bodies import countable_thesis_ids

    countable = countable_thesis_ids()
    cdir = catalog_dir()
    twos: list[tuple[float, str]] = []
    threes: list[tuple[float, str]] = []
    have: set[str] = set()
    for row in combo_thesis_records():
        lid = str(row.get("logic_id") or "")
        if lid and lid not in countable:
            continue
        gates = sorted(
            str(x) for x in (row.get("gates") or []) if str(x).strip()
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
    """Recorded empty AND-sets. Prefer-subset reserved in assemble. Does not GO."""
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


def sparse_prefer_subset_avoid() -> list[str]:
    """SPARSE AND-sets whose gates ⊆ prefer seeds. Parked prefer clones first."""
    from research.unique_logic.propose_review_tables import PROPOSE_PROMPT_PREFER_GATES

    prefer = set(PROPOSE_PROMPT_PREFER_GATES)
    out: list[str] = []
    have: set[str] = set()
    for token in sparse_gate_set_avoid():
        gates = set(token.split("+"))
        if not gates <= prefer:
            continue
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
    if any(w in blob for w in PROPOSE_TWEAK_WORDS) and "factor" not in blob:
        if not proposal.get("datasets") and not proposal.get("datasets_used"):
            return True
    return False


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
    timeout: int = 300,
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
    avoid = assemble_why_avoid(why_avoid)
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
    "CATALOG_GATE_SET_AVOID_LIMIT",
    "PROPOSE_ALLOWED_DATASETS",
    "PROPOSE_WHY_AVOID_LIMIT",
    "assemble_why_avoid",
    "catalog_gate_set_avoid",
    "catalog_prefer_and_avoid",
    "catalog_prefer_pair_avoid",
    "catalog_prefer_triple_avoid",
    "sparse_gate_set_avoid",
    "sparse_prefer_subset_avoid",
    "invoke_cf_propose_thesis",
    "reject_window_tweak",
    "review_proposal_row",
]
