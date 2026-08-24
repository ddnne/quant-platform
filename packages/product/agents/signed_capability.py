"""Signed isolation capability envelope.

Runtime isolation (process today, a future isolate later) accepts only a
capability issued by :func:`issue_isolation_capability`. Callers cannot fill a
public dataclass to self-authorize. This is not a Cloudflare Sandbox deploy.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
from datetime import datetime, timezone
from typing import Iterable, Mapping

_ISSUE_TOKEN = object()
_SHA256_HASH = re.compile(r"^sha256:[0-9a-f]{64}$")

DEFAULT_AUDIENCE = "process-isolated-runner"


class IsolationRejected(RuntimeError):
    """Raised when isolation policy or the capability envelope forbids an action."""


class SignedIsolationCapability:
    """Opaque signed capability. Only :func:`issue_isolation_capability` may construct."""

    __slots__ = (
        "_audience",
        "_scope",
        "_expires_at",
        "_plan_hash",
        "_snapshot_hash",
        "_mac",
    )

    def __init__(self, *, _factory_token: object = None, **_ignored: object) -> None:
        if _factory_token is not _ISSUE_TOKEN:
            raise IsolationRejected(
                "SignedIsolationCapability must be issued by issue_isolation_capability"
            )

    def __setattr__(self, name: str, value: object) -> None:
        raise IsolationRejected("signed capability is immutable")

    @property
    def audience(self) -> str:
        return str(object.__getattribute__(self, "_audience"))

    @property
    def scope(self) -> frozenset[str]:
        return frozenset(object.__getattribute__(self, "_scope"))

    @property
    def expires_at(self) -> str:
        return str(object.__getattribute__(self, "_expires_at"))

    @property
    def plan_hash(self) -> str:
        return str(object.__getattribute__(self, "_plan_hash"))

    @property
    def snapshot_hash(self) -> str:
        return str(object.__getattribute__(self, "_snapshot_hash"))


def _isolation_secret(explicit: bytes | None) -> bytes:
    if explicit:
        if not isinstance(explicit, (bytes, bytearray)):
            raise IsolationRejected("isolation HMAC secret must be bytes")
        secret = bytes(explicit)
        if not secret:
            raise IsolationRejected("isolation HMAC secret must be bytes")
        return secret
    env = os.environ.get("QUANT_ISOLATION_HMAC_SECRET", "").strip()
    if env:
        return env.encode("utf-8")
    raise IsolationRejected("isolation HMAC secret not configured")


def _parse_expiry(value: str | datetime) -> datetime:
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise IsolationRejected("capability expiry must be timezone-aware")
    return dt.astimezone(timezone.utc)


def _require_hash(name: str, value: str) -> str:
    text = str(value)
    if not _SHA256_HASH.fullmatch(text):
        raise IsolationRejected(f"{name} must be sha256:<64 hex chars>")
    return text


def _canonical_body(
    *,
    audience: str,
    scope: Iterable[str],
    expires_at: str,
    plan_hash: str,
    snapshot_hash: str,
) -> dict[str, object]:
    return {
        "audience": audience,
        "scope": sorted(scope),
        "expires_at": expires_at,
        "plan_hash": plan_hash,
        "snapshot_hash": snapshot_hash,
    }


def _sign(body: Mapping[str, object], secret: bytes) -> str:
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
    dig = hmac.new(secret, raw, hashlib.sha256).digest()
    return "hmac-sha256:" + base64.b64encode(dig).decode("ascii")


def issue_isolation_capability(
    *,
    audience: str,
    scope: Iterable[str],
    expires_at: str | datetime,
    plan_hash: str,
    snapshot_hash: str,
    hmac_secret: bytes | None = None,
    now: datetime | None = None,
) -> SignedIsolationCapability:
    """Issue a signed capability. Does not grant mass research or a sandbox deploy."""
    aud = str(audience).strip()
    if not aud:
        raise IsolationRejected("audience required")
    tools = frozenset(str(t).strip() for t in scope if str(t).strip())
    if not tools:
        raise IsolationRejected("scope must contain at least one tool id")
    expiry = _parse_expiry(expires_at)
    clock = now or datetime.now(timezone.utc)
    if expiry <= clock:
        raise IsolationRejected("capability expiry must be in the future")
    plan = _require_hash("plan_hash", plan_hash)
    snapshot = _require_hash("snapshot_hash", snapshot_hash)
    secret = _isolation_secret(hmac_secret)
    expires_iso = expiry.isoformat()
    body = _canonical_body(
        audience=aud,
        scope=tools,
        expires_at=expires_iso,
        plan_hash=plan,
        snapshot_hash=snapshot,
    )
    cap = SignedIsolationCapability(_factory_token=_ISSUE_TOKEN)
    object.__setattr__(cap, "_audience", aud)
    object.__setattr__(cap, "_scope", tools)
    object.__setattr__(cap, "_expires_at", expires_iso)
    object.__setattr__(cap, "_plan_hash", plan)
    object.__setattr__(cap, "_snapshot_hash", snapshot)
    object.__setattr__(cap, "_mac", _sign(body, secret))
    return cap


def verify_isolation_capability(
    capability: object,
    *,
    audience: str,
    tool_id: str,
    plan_hash: str,
    snapshot_hash: str,
    hmac_secret: bytes | None = None,
    now: datetime | None = None,
) -> SignedIsolationCapability:
    """Accept only a factory-issued envelope whose MAC, binding, and expiry check."""
    if type(capability) is not SignedIsolationCapability:
        raise IsolationRejected("capability is not a signed isolation capability")
    secret = _isolation_secret(hmac_secret)
    body = _canonical_body(
        audience=capability.audience,
        scope=capability.scope,
        expires_at=capability.expires_at,
        plan_hash=capability.plan_hash,
        snapshot_hash=capability.snapshot_hash,
    )
    expected = _sign(body, secret)
    mac = str(object.__getattribute__(capability, "_mac"))
    if not hmac.compare_digest(mac.encode("ascii"), expected.encode("ascii")):
        raise IsolationRejected("capability signature mismatch")
    clock = now or datetime.now(timezone.utc)
    if _parse_expiry(capability.expires_at) <= clock:
        raise IsolationRejected("capability expired")
    if capability.audience != str(audience):
        raise IsolationRejected("capability audience mismatch")
    if str(tool_id) not in capability.scope:
        raise IsolationRejected(f"tool id not in capability scope: {tool_id}")
    if capability.plan_hash != _require_hash("plan_hash", plan_hash):
        raise IsolationRejected("capability plan_hash mismatch")
    if capability.snapshot_hash != _require_hash("snapshot_hash", snapshot_hash):
        raise IsolationRejected("capability snapshot_hash mismatch")
    return capability


__all__ = [
    "DEFAULT_AUDIENCE",
    "IsolationRejected",
    "SignedIsolationCapability",
    "issue_isolation_capability",
    "verify_isolation_capability",
]
