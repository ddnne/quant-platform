"""Sleeve/meta majority compares. Descriptive only. Not a pass / not GO."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

COMPARE_COMPOSITION_IDS: tuple[str, ...] = (
    "basket_theme_fund",
    "basket_theme_flow",
    "basket_event_fund",
    "meta_fund_flow",
    "meta_fund_event",
    "meta_fund_flow_event",
)


def compare_basket_summaries(
    summary_a: Mapping[str, Any],
    summary_b: Mapping[str, Any],
    *,
    label_a: str,
    label_b: str,
) -> dict[str, Any]:
    by_a = {
        str(r.get("basket_id")): r
        for r in (summary_a.get("baskets") or [])
        if r.get("basket_id")
    }
    by_b = {
        str(r.get("basket_id")): r
        for r in (summary_b.get("baskets") or [])
        if r.get("basket_id")
    }
    rows: list[dict[str, Any]] = []
    for bid in sorted(set(by_a) | set(by_b)):
        a = by_a.get(bid) or {}
        b = by_b.get(bid) or {}
        pa, na = int(a.get("n_pos_windows") or 0), int(a.get("n_neg_windows") or 0)
        pb, nb = int(b.get("n_pos_windows") or 0), int(b.get("n_neg_windows") or 0)
        maj_a = 1 if pa > na else (-1 if na > pa else 0)
        maj_b = 1 if pb > nb else (-1 if nb > pb else 0)
        if maj_a == 0 or maj_b == 0:
            kind = "mixed"
        elif maj_a != maj_b:
            kind = "flipped"
        else:
            kind = "stable_majority"
        rows.append(
            {
                "basket_id": bid,
                "rule": a.get("rule") or b.get("rule"),
                "class": kind,
                label_a: {"n_pos": pa, "n_neg": na},
                label_b: {"n_pos": pb, "n_neg": nb},
                "primary_candidate_now": bool(
                    (b.get("primary_candidate") if b else a.get("primary_candidate"))
                ),
            }
        )
    stable = [r["basket_id"] for r in rows if r["class"] == "stable_majority"]
    flipped = [r["basket_id"] for r in rows if r["class"] == "flipped"]
    mixed = [r["basket_id"] for r in rows if r["class"] == "mixed"]
    return {
        "version": "sleeve-universe-stability/v1",
        "label_a": label_a,
        "label_b": label_b,
        "stable_majority": stable,
        "flipped": flipped,
        "mixed": mixed,
        "preferred_materials": [
            "basket_theme_fund",
            "basket_theme_flow",
        ],
        "sleeves": rows,
        "promote_as_main": False,
        "go": False,
        "not_a_pass": True,
    }


def classify_sleeves_three_n(
    summary_50: Mapping[str, Any],
    summary_80: Mapping[str, Any],
    summary_100: Mapping[str, Any],
) -> dict[str, Any]:
    def _rows(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            str(r.get("basket_id")): r
            for r in (summary.get("baskets") or [])
            if r.get("basket_id")
        }

    def _maj(row: Mapping[str, Any] | None) -> int:
        if not row:
            return 0
        return _majority_sign(
            int(row.get("n_pos_windows") or 0),
            int(row.get("n_neg_windows") or 0),
        )

    a, b, c = _rows(summary_50), _rows(summary_80), _rows(summary_100)
    ids = sorted(set(a) | set(b) | set(c))
    sleeves: list[dict[str, Any]] = []
    stable_mid: list[str] = []
    dilutes: list[str] = []
    unstable: list[str] = []
    for bid in ids:
        m50, m80, m100 = _maj(a.get(bid)), _maj(b.get(bid)), _maj(c.get(bid))
        mid_ok = m50 == m80 == 1
        flipped = m50 != 0 and m80 != 0 and m50 != m80
        if flipped or (mid_ok and m100 == -1):
            kind = "unstable"
            unstable.append(bid)
        elif mid_ok and m100 != 1:
            kind = "dilutes_at_large"
            dilutes.append(bid)
            stable_mid.append(bid)
        elif mid_ok:
            kind = "stable_mid"
            stable_mid.append(bid)
        else:
            kind = "mixed"
        sleeves.append(
            {
                "basket_id": bid,
                "class": kind,
                "univ50_maj": m50,
                "univ80_maj": m80,
                "univ100_maj": m100,
                "univ50": {
                    "n_pos": int((a.get(bid) or {}).get("n_pos_windows") or 0),
                    "n_neg": int((a.get(bid) or {}).get("n_neg_windows") or 0),
                },
                "univ80": {
                    "n_pos": int((b.get(bid) or {}).get("n_pos_windows") or 0),
                    "n_neg": int((b.get(bid) or {}).get("n_neg_windows") or 0),
                },
                "univ100": {
                    "n_pos": int((c.get(bid) or {}).get("n_pos_windows") or 0),
                    "n_neg": int((c.get(bid) or {}).get("n_neg_windows") or 0),
                },
            }
        )
    return {
        "version": "sleeve-universe-stability/v2",
        "stable_mid": stable_mid,
        "dilutes_at_large": dilutes,
        "unstable": unstable,
        "preferred_materials": ["basket_theme_fund", "basket_theme_flow"],
        "sleeves": sleeves,
        "univ100_is_not_stable": True,
        "promote_as_main": False,
        "go": False,
        "not_a_pass": True,
        "primary_candidate_is_not_a_pass": True,
    }


def _index_composition(summary: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in list(summary.get("baskets") or []):
        if not isinstance(r, Mapping):
            continue
        bid = str(r.get("basket_id") or r.get("meta_id") or "")
        if bid:
            out[bid] = dict(r)
    return out


def _majority_sign(n_pos: int, n_neg: int) -> int:
    if n_pos > n_neg:
        return 1
    if n_neg > n_pos:
        return -1
    return 0


def _compare_composition_rows(
    summary_a: Mapping[str, Any],
    summary_b: Mapping[str, Any],
    *,
    ids: Sequence[str],
    label_a: str,
    label_b: str,
    a_better_class: str,
    b_better_class: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    a = _index_composition(summary_a)
    b = _index_composition(summary_b)
    rows: list[dict[str, Any]] = []
    b_majority_better: list[str] = []
    for bid in ids:
        ha, hb = a.get(bid) or {}, b.get(bid) or {}
        pa, na = int(ha.get("n_pos_windows") or 0), int(ha.get("n_neg_windows") or 0)
        pb, nb = int(hb.get("n_pos_windows") or 0), int(hb.get("n_neg_windows") or 0)
        maj_a = _majority_sign(pa, na)
        maj_b = _majority_sign(pb, nb)
        if maj_a == 0 and maj_b == 0:
            kind = "both_mixed"
        elif maj_a == maj_b:
            kind = "same_majority"
        elif maj_b == 1 and maj_a != 1:
            kind = b_better_class
            b_majority_better.append(bid)
        elif maj_a == 1 and maj_b != 1:
            kind = a_better_class
        else:
            kind = "diverged"
        rows.append(
            {
                "id": bid,
                "class": kind,
                label_a: {"n_pos": pa, "n_neg": na, "maj": maj_a},
                label_b: {"n_pos": pb, "n_neg": nb, "maj": maj_b},
            }
        )
    return rows, b_majority_better


def _composition_compare(
    summary_a: Mapping[str, Any],
    summary_b: Mapping[str, Any],
    *,
    version: str,
    job_a: str,
    job_b: str,
    label_a: str,
    label_b: str,
    a_better_class: str,
    b_better_class: str,
    ids: Sequence[str] | None,
) -> dict[str, Any]:
    want = tuple(ids) if ids is not None else COMPARE_COMPOSITION_IDS
    rows, liq_majority_better = _compare_composition_rows(
        summary_a,
        summary_b,
        ids=want,
        label_a=label_a,
        label_b=label_b,
        a_better_class=a_better_class,
        b_better_class=b_better_class,
    )
    return {
        "version": version,
        job_a: summary_a.get("job_id"),
        job_b: summary_b.get("job_id"),
        "ids": list(want),
        "liq_majority_better": liq_majority_better,
        "rows": rows,
        "liq_print_is_not_stable": True,
        "not_a_pass": True,
        "go": False,
        "promote_as_main": False,
    }


def compare_headn_vs_liq(
    summary_headn: Mapping[str, Any],
    summary_liq: Mapping[str, Any],
    *,
    ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    return _composition_compare(
        summary_headn,
        summary_liq,
        version="composition-compare/v1",
        job_a="head_n_job",
        job_b="liq_job",
        label_a="head_n",
        label_b="liq",
        a_better_class="headn_majority_better",
        b_better_class="liq_majority_better",
        ids=ids,
    )


def compare_mid_vs_liq(
    summary_mid: Mapping[str, Any],
    summary_liq: Mapping[str, Any],
    *,
    ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    return _composition_compare(
        summary_mid,
        summary_liq,
        version="composition-compare/v2",
        job_a="mid_n_job",
        job_b="liq_job",
        label_a="mid_n",
        label_b="liq",
        a_better_class="mid_majority_better",
        b_better_class="liq_majority_better",
        ids=ids,
    )
