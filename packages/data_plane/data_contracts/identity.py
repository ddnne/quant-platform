"""Contract-driven, cross-runtime row identity and PIT timestamps.

The TypeScript mirror imports the same JSON contract.  ``canonical_json`` is
defined to match JavaScript JSON number rendering and UTF-16 object-key order,
which makes the SHA-256 fallback byte-identical in Python and Workers.

Finite numbers follow ECMAScript ``JSON.stringify`` (ordinary fractions,
negatives, ``-0``, the ``1e-6`` / ``1e21`` exponent thresholds, and integers
coerced through binary64).  Python-generated canonical bytes, payload strings,
and digests from before the fractional-number fix are not trustworthy when they
contain affected fractions such as ``0.45`` / ``0.11``; this module does not
rewrite stored rows.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import re
from typing import Any, Mapping, Sequence

from .loader import DatasetContract, contract_for
from .source_capability import (
    SourceCapabilityContract,
    source_capability_contract_for,
)

JST = timezone(timedelta(hours=9))
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LAG_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?)?$")


def _utf16_sort_key(value: str) -> bytes:
    return value.encode("utf-16-be", errors="surrogatepass")


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _js_number(value: int | float) -> str:
    """Render a Python JSON number like ECMAScript ``JSON.stringify``.

    J-Quants JSON uses interoperable finite numbers.  Coercing integers through
    binary64 intentionally matches JavaScript's single ``number`` type.  Stripping
    leading zeros from the digit string must also move the decimal point;
    otherwise ``0.45`` is emitted as ``4.5``.
    """
    number = float(value)
    if not math.isfinite(number):
        return "null"
    if number == 0:
        return "0"
    negative = number < 0
    raw = repr(abs(number)).lower()
    if "e" in raw:
        mantissa, exp_text = raw.split("e", 1)
        exponent = int(exp_text)
    else:
        mantissa, exponent = raw, 0
    integer, _dot, fraction = mantissa.partition(".")
    digits = integer + fraction
    leading_zeros = len(digits) - len(digits.lstrip("0"))
    digits = digits.lstrip("0") or "0"
    decimal_pos = len(integer) + exponent - leading_zeros
    magnitude = abs(number)
    if 1e-6 <= magnitude < 1e21:
        if decimal_pos <= 0:
            rendered = "0." + ("0" * -decimal_pos) + digits
        elif decimal_pos >= len(digits):
            rendered = digits + ("0" * (decimal_pos - len(digits)))
        else:
            rendered = digits[:decimal_pos] + "." + digits[decimal_pos:]
        if "." in rendered:
            rendered = rendered.rstrip("0").rstrip(".")
    else:
        significant = digits.rstrip("0") or "0"
        sci_exp = decimal_pos - 1
        rendered = significant[0]
        if len(significant) > 1:
            rendered += "." + significant[1:]
        rendered += "e" + ("+" if sci_exp >= 0 else "") + str(sci_exp)
    return ("-" if negative else "") + rendered


def canonical_json(value: Any) -> str:
    """Serialize an interoperable JSON value to deterministic UTF-8 text."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, (int, float)):
        return _js_number(value)
    if isinstance(value, str):
        return _json_string(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_json(v) for v in value) + "]"
    if isinstance(value, Mapping):
        items: list[str] = []
        for key in sorted((str(k) for k in value), key=_utf16_sort_key):
            items.append(_json_string(key) + ":" + canonical_json(value[key]))
        return "{" + ",".join(items) + "}"
    raise TypeError(f"not an interoperable JSON value: {type(value).__name__}")


def sha256_fallback(row: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(canonical_json(row).encode("utf-8")).hexdigest()
    return f"hash:sha256:{digest}"


def _pick(
    row: Mapping[str, Any], contract: DatasetContract, field: str
) -> Any | None:
    for candidate in contract.aliases_for(field):
        for key in (candidate, candidate.lower()):
            value = row.get(key)
            if value is not None and value != "":
                return value
    return None


def natural_key(row: Mapping[str, Any], dataset_id: str) -> str:
    """Return the contract-selected natural key or SHA-256 row fallback.

    Composite keys are all-or-nothing.  A missing discriminator uses the row
    hash instead of a partial key that could collapse distinct observations.
    """
    contract = contract_for(dataset_id)
    picked: dict[str, Any] = {}
    for field in contract.natural_key_fields:
        value = _pick(row, contract, field)
        if value is None or value == "":
            return sha256_fallback(row)
        picked[field] = value
    return canonical_json(picked)


def session_close_jst(date_yyyy_mm_dd: str, *, session: str | None = None) -> str:
    _parse_date(date_yyyy_mm_dd)
    if session == "morning":
        close = "11:30:00"
    else:
        close = "15:00:00" if date_yyyy_mm_dd < "2024-11-05" else "15:30:00"
    return f"{date_yyyy_mm_dd}T{close}+09:00"


def _parse_date(value: str) -> datetime:
    if not _DATE_RE.fullmatch(value):
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}")
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=JST)
    except ValueError as exc:
        raise ValueError(f"expected YYYY-MM-DD, got {value!r}") from exc


def _date_start(value: Any) -> str | None:
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return None
    try:
        _parse_date(value)
    except ValueError:
        return None
    return f"{value}T00:00:00+09:00"


def _timestamp_from_fields(
    row: Mapping[str, Any], contract: DatasetContract, fields: Sequence[str]
) -> str | None:
    if not fields:
        return None
    first = _pick(row, contract, fields[0])
    if not isinstance(first, str) or not first:
        return None
    if "T" in first or " " in first:
        return first
    if len(fields) < 2:
        return None
    second = _pick(row, contract, fields[1])
    if not isinstance(second, str) or not second or not _DATE_RE.fullmatch(first):
        return None
    try:
        _parse_date(first)
    except ValueError:
        return None
    clock = second
    if re.fullmatch(r"\d{2}:\d{2}", clock):
        clock += ":00"
    if not re.fullmatch(r"\d{2}:\d{2}:\d{2}(?:\.\d+)?", clock):
        return None
    return f"{first}T{clock}+09:00"


def event_time_for(row: Mapping[str, Any], dataset_id: str) -> str | None:
    contract = contract_for(dataset_id)
    if contract.event_time_policy == "session_close":
        value = _pick(row, contract, contract.event_time_fields[0])
        if isinstance(value, str) and _DATE_RE.fullmatch(value):
            try:
                return session_close_jst(value, session=contract.session)
            except ValueError:
                return None
        return None
    if contract.event_time_policy == "explicit_timestamp_field":
        instant = _timestamp_from_fields(row, contract, contract.event_time_fields)
        if instant is not None:
            return instant
        value = _pick(row, contract, contract.event_time_fields[0])
        return _date_start(value)
    if contract.event_time_policy == "observation_date":
        value = _pick(row, contract, contract.event_time_fields[0])
        return _date_start(value)
    return None


def _disclosure_available_at(
    row: Mapping[str, Any], contract: DatasetContract
) -> str | None:
    field = contract.availability_field
    if not field:
        return None
    fields = tuple(field.split("+"))
    instant = _timestamp_from_fields(row, contract, fields)
    if instant is not None:
        return instant
    value = _pick(row, contract, fields[0])
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return None
    try:
        day = _parse_date(value) + timedelta(days=1)
    except ValueError:
        return None
    return day.strftime("%Y-%m-%dT00:00:00+09:00")


def _known_lag_available_at(
    row: Mapping[str, Any], contract: DatasetContract
) -> str | None:
    lag = contract.known_publication_lag
    event = event_time_for(row, contract.dataset_id)
    if lag is None or event is None:
        return None
    match = _LAG_RE.fullmatch(lag)
    if not match:
        return None
    try:
        dt = datetime.fromisoformat(event)
    except ValueError:
        return None
    dt += timedelta(days=int(match.group(1) or 0), hours=int(match.group(2) or 0))
    return dt.isoformat(timespec="seconds")


def _source_capability_for(dataset_id: str) -> SourceCapabilityContract | None:
    try:
        return source_capability_contract_for(dataset_id)
    except KeyError:
        return None


def _event_or_session_date(
    row: Mapping[str, Any], contract: DatasetContract
) -> str | None:
    field = None
    if contract.event_time_fields:
        field = contract.event_time_fields[0]
    elif contract.availability_field:
        field = contract.availability_field.split("+")[0]
    if not field:
        return None
    value = _pick(row, contract, field)
    if not isinstance(value, str) or not _DATE_RE.fullmatch(value):
        return None
    try:
        _parse_date(value)
    except ValueError:
        return None
    return value


def _before_official_availability(
    row: Mapping[str, Any], dataset_id: str, contract: DatasetContract
) -> bool:
    capability = _source_capability_for(dataset_id)
    if capability is None:
        return False
    day = _event_or_session_date(row, contract)
    if day is None:
        return False
    return day < capability.earliest_official_availability


def available_at_for(
    row: Mapping[str, Any], dataset_id: str, ingested_at: str
) -> str:
    """Compute contract-selected availability, always failing safe to ingest.

    ingest_time_conservative keeps ingested_at when the historical publication
    instant is unknown (master Date is observation day, not publication).
    SourceCapabilityContract is consulted so a pre-official event/session date
    is not rewritten into a Date-derived available_at that would make those
    rows look PIT-eligible. Fail-safe remains ingested_at. PIT query clamp
    (not this function) is the membership gate for as_of before official start.
    """
    contract = contract_for(dataset_id)
    policy = contract.available_at_policy
    # Consult official start even when the timestamp stays ingest-time.
    pre_official = _before_official_availability(row, dataset_id, contract)
    if pre_official and policy in (
        "ingest_time_conservative",
        "calendar_prepublished",
    ):
        # Do not mint Date-derived PIT eligibility for pre-official rows.
        # Tip-only AM session_close is left to its policy so this function
        # does not invent historical AM/earnings eligibility.
        return ingested_at
    if policy == "session_close":
        value = _pick(row, contract, contract.availability_field or "Date")
        if isinstance(value, str) and _DATE_RE.fullmatch(value):
            try:
                return session_close_jst(value, session=contract.session)
            except ValueError:
                pass
    elif policy == "explicit_timestamp_field":
        field = contract.availability_field
        if field:
            instant = _timestamp_from_fields(row, contract, tuple(field.split("+")))
            if instant is not None:
                return instant
    elif policy == "explicit_disclosure_date":
        instant = _disclosure_available_at(row, contract)
        if instant is not None:
            return instant
    elif policy == "known_publication_lag":
        instant = _known_lag_available_at(row, contract)
        if instant is not None:
            return instant
    # calendar_prepublished and ingest_time_conservative both deliberately
    # retain ingest time when the historical publication instant is unknown.
    return ingested_at


__all__ = [
    "available_at_for",
    "canonical_json",
    "event_time_for",
    "natural_key",
    "session_close_jst",
    "sha256_fallback",
]
