"""Closed TOPIX scale vocabulary for personal DRAFT research.

Keep one tiny normalization surface in ``data_contracts`` so ingestion and
product resolution cannot silently disagree about membership.
"""

from __future__ import annotations

import hashlib
import json
from types import MappingProxyType
from typing import Any, Mapping


PERSONAL_HISTORY_SCOPE_ID = "topix_all"
PERSONAL_HISTORY_SCOPE_VERSION = "personal-topix-scale-history/v1"

TOPIX_CORE30 = "TOPIX Core30"
TOPIX_LARGE70 = "TOPIX Large70"
TOPIX_MID400 = "TOPIX Mid400"
TOPIX_SMALL_1 = "TOPIX Small 1"
TOPIX_SMALL_2 = "TOPIX Small 2"
TOPIX_SCALE_CATEGORIES: tuple[str, ...] = (
    TOPIX_CORE30,
    TOPIX_LARGE70,
    TOPIX_MID400,
    TOPIX_SMALL_1,
    TOPIX_SMALL_2,
)

_ALIASES: Mapping[str, str] = MappingProxyType(
    {
        "topix core30": TOPIX_CORE30,
        "topix large70": TOPIX_LARGE70,
        "topix mid400": TOPIX_MID400,
        "topix small 2": TOPIX_SMALL_2,
        "topix small2": TOPIX_SMALL_2,
        "topix small 1": TOPIX_SMALL_1,
        "topix small1": TOPIX_SMALL_1,
    }
)


def canonical_topix_scale_category(value: Any) -> str | None:
    """Return one canonical TOPIX scale label, or ``None`` when outside it."""

    text = " ".join(str(value or "").strip().split())
    if not text or text == "-":
        return None
    return _ALIASES.get(text.lower())


PERSONAL_HISTORY_SCOPE_DOCUMENT: Mapping[str, Any] = MappingProxyType(
    {
        "scope_id": PERSONAL_HISTORY_SCOPE_ID,
        "scope_version": PERSONAL_HISTORY_SCOPE_VERSION,
        "membership_source": "equities_master.ScaleCategory",
        "categories": TOPIX_SCALE_CATEGORIES,
        "decision_semantics": "dated_pit_master_snapshot",
        "research_state": "PERSONAL_DRAFT",
        "controlled_live_eligibility": "FORBIDDEN",
    }
)


def _canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


PERSONAL_HISTORY_SCOPE_DIGEST = _canonical_digest(
    dict(PERSONAL_HISTORY_SCOPE_DOCUMENT)
)


__all__ = [
    "PERSONAL_HISTORY_SCOPE_DIGEST",
    "PERSONAL_HISTORY_SCOPE_DOCUMENT",
    "PERSONAL_HISTORY_SCOPE_ID",
    "PERSONAL_HISTORY_SCOPE_VERSION",
    "TOPIX_CORE30",
    "TOPIX_LARGE70",
    "TOPIX_MID400",
    "TOPIX_SCALE_CATEGORIES",
    "TOPIX_SMALL_1",
    "TOPIX_SMALL_2",
    "canonical_topix_scale_category",
]
