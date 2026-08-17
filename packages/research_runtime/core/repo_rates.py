"""Load daily JSDA Tokyo repo rates for paper financing via PIT.

W86 / w0816u — paper path auto-loads date-matched rates when financing is
enabled and no explicit ``repo_rates_by_date`` is supplied. Gaps are
disclosed only (no ffill / invent).

This module lives in ``core`` so :mod:`strategies.paper` can call it without
importing ``pit`` directly (strategies static boundary forbids ``pit``).
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

import pit
from pit.query import resolve_db_path

from .costs import PAPER_REPO_TENOR_PREFERENCE, rates_by_date_from_repo_rows
from .execution import close_as_of


def load_repo_rates_by_date_for_paper(
    *,
    db_path: Any = None,
    start: str | None = None,
    end: str | None = None,
    as_of: str | None = None,
    visibility: str = "tip",
    prefer_tenors: Sequence[str] | None = PAPER_REPO_TENOR_PREFERENCE,
    get_jsda_repo_rates_fn: Any = None,
) -> dict[str, Any]:
    """Load ``{YYYY-MM-DD: rate_pct}`` for paper short/leverage financing.

    Parameters
    ----------
    db_path:
        Structured SQLite (paper seed or ingestion). Resolved via PIT path helper.
    start, end:
        Optional inclusive ``as_of_date`` bounds (YYYY-MM-DD).
    as_of:
        Explicit PIT visibility clock. When omitted, ``visibility`` chooses:
        * ``\"tip\"`` (default) — far-future as_of so research paper DBs whose
          repo rows carry **backfill** ``available_at`` remain usable for
          **date-matched** financing (keyed by ``as_of_date``, never ffilled).
        * ``\"period_end\"`` — session close of ``end`` (strict PIT; historical
          windows hide rows published after the period).
    visibility:
        ``tip`` | ``period_end`` (ignored when ``as_of`` is supplied).
    prefer_tenors:
        Ordered tenor preference (overnight T+0 first for paper financing).
    get_jsda_repo_rates_fn:
        Injected PIT getter for tests.

    Returns
    -------
    dict with ``rates_by_date``, coverage metadata, and gap policy fields.
    Never invent-fills missing dates.
    """
    resolved = resolve_db_path(db_path)
    vis = str(visibility or "tip").strip().lower()
    if as_of is None:
        if vis == "period_end" and end:
            as_of = close_as_of(str(end)[:10])
        else:
            # Tip visibility: financing series is date-matched by as_of_date.
            # Research paper seeds often stamp available_at at extract time
            # (not the historical publication clock); tip load keeps those
            # rows visible without inventing rates for gap dates.
            as_of = "2099-12-31T15:30:00+09:00"
            vis = "tip"

    getter = get_jsda_repo_rates_fn
    if getter is None:
        getter = pit.get_jsda_repo_rates

    result = getter(
        as_of,
        from_event=start,
        to_event=end,
        db_path=resolved,
    )
    if hasattr(result, "rows"):
        rows: Sequence[Mapping[str, Any]] = list(result.rows or [])
    elif isinstance(result, Mapping) and "rows" in result:
        rows = list(result["rows"] or [])
    elif isinstance(result, Sequence) and not isinstance(result, (str, bytes)):
        rows = list(result)  # type: ignore[arg-type]
    else:
        rows = []

    pack = rates_by_date_from_repo_rows(rows, prefer_tenors=prefer_tenors)
    out: dict[str, Any] = {
        "kind": "paper_repo_rate_series",
        "rates_by_date": dict(pack["rates_by_date"]),
        "n_obs": int(pack["n_obs"]),
        "n_input_rows": int(pack["n_input_rows"]),
        "chosen_tenor": pack.get("chosen_tenor"),
        "prefer_tenors": list(pack.get("prefer_tenors") or []),
        "as_of": str(as_of),
        "visibility": vis if as_of else "explicit",
        "start": str(start)[:10] if start else None,
        "end": str(end)[:10] if end else None,
        "db_path": str(resolved),
        "load_path": "pit.get_jsda_repo_rates",
        "series_present": bool(pack["rates_by_date"]),
        "gap_policy": "disclose_only_no_ffill_no_invent",
        "ffill_applied": False,
        "invent_fill": False,
        "note": (
            "Date-matched JSDA Tokyo repo rates for paper financing. "
            "Keyed by as_of_date; missing trading days are gaps (charge 0); "
            "never ffilled. Default tip visibility admits research seeds whose "
            "available_at is extract-time (not inventing rates)."
        ),
    }
    return out
