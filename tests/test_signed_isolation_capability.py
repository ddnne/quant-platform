"""SignedIsolationCapability is factory-issued; callers cannot self-authorize."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

from agents.signed_capability import (
    DEFAULT_AUDIENCE,
    IsolationRejected,
    SignedIsolationCapability,
    issue_isolation_capability,
    verify_isolation_capability,
)

_SECRET = b"isolation-capability-test-hmac"
_OTHER = b"isolation-capability-other-hmac"
_HASH = "sha256:" + ("ab" * 32)
_HASH_B = "sha256:" + ("cd" * 32)
_EXPIRES = "2099-01-01T00:00:00+00:00"


def _issue(**kwargs: object) -> SignedIsolationCapability:
    params: dict[str, object] = {
        "audience": DEFAULT_AUDIENCE,
        "scope": frozenset({"true"}),
        "expires_at": _EXPIRES,
        "plan_hash": _HASH,
        "snapshot_hash": _HASH,
        "hmac_secret": _SECRET,
    }
    params.update(kwargs)
    return issue_isolation_capability(**params)  # type: ignore[arg-type]


def test_capability_is_not_a_public_dataclass():
    assert not dataclasses.is_dataclass(SignedIsolationCapability)
    with pytest.raises(IsolationRejected, match="issued"):
        SignedIsolationCapability(
            audience=DEFAULT_AUDIENCE,
            scope=frozenset({"true"}),
            expires_at=_EXPIRES,
            plan_hash=_HASH,
            snapshot_hash=_HASH,
        )


def test_issue_and_verify_round_trip():
    cap = _issue()
    out = verify_isolation_capability(
        cap,
        audience=DEFAULT_AUDIENCE,
        tool_id="true",
        plan_hash=_HASH,
        snapshot_hash=_HASH,
        hmac_secret=_SECRET,
    )
    assert out is cap
    assert cap.audience == DEFAULT_AUDIENCE
    assert cap.scope == frozenset({"true"})
    assert cap.plan_hash == _HASH
    assert cap.snapshot_hash == _HASH


def test_verify_rejects_dict_and_wrong_type():
    with pytest.raises(IsolationRejected, match="not a signed"):
        verify_isolation_capability(
            {
                "audience": DEFAULT_AUDIENCE,
                "scope": ["true"],
                "expires_at": _EXPIRES,
                "plan_hash": _HASH,
                "snapshot_hash": _HASH,
            },
            audience=DEFAULT_AUDIENCE,
            tool_id="true",
            plan_hash=_HASH,
            snapshot_hash=_HASH,
            hmac_secret=_SECRET,
        )


def test_verify_rejects_wrong_secret_audience_scope_and_hashes():
    cap = _issue()
    with pytest.raises(IsolationRejected, match="signature"):
        verify_isolation_capability(
            cap,
            audience=DEFAULT_AUDIENCE,
            tool_id="true",
            plan_hash=_HASH,
            snapshot_hash=_HASH,
            hmac_secret=_OTHER,
        )
    with pytest.raises(IsolationRejected, match="audience"):
        verify_isolation_capability(
            cap,
            audience="cloudflare-isolate",
            tool_id="true",
            plan_hash=_HASH,
            snapshot_hash=_HASH,
            hmac_secret=_SECRET,
        )
    with pytest.raises(IsolationRejected, match="scope"):
        verify_isolation_capability(
            cap,
            audience=DEFAULT_AUDIENCE,
            tool_id="python",
            plan_hash=_HASH,
            snapshot_hash=_HASH,
            hmac_secret=_SECRET,
        )
    with pytest.raises(IsolationRejected, match="plan_hash"):
        verify_isolation_capability(
            cap,
            audience=DEFAULT_AUDIENCE,
            tool_id="true",
            plan_hash=_HASH_B,
            snapshot_hash=_HASH,
            hmac_secret=_SECRET,
        )
    with pytest.raises(IsolationRejected, match="snapshot_hash"):
        verify_isolation_capability(
            cap,
            audience=DEFAULT_AUDIENCE,
            tool_id="true",
            plan_hash=_HASH,
            snapshot_hash=_HASH_B,
            hmac_secret=_SECRET,
        )


def test_expired_capability_rejected():
    cap = _issue(expires_at="2099-06-01T00:00:00+00:00")
    later = datetime(2099, 7, 1, tzinfo=timezone.utc)
    with pytest.raises(IsolationRejected, match="expired"):
        verify_isolation_capability(
            cap,
            audience=DEFAULT_AUDIENCE,
            tool_id="true",
            plan_hash=_HASH,
            snapshot_hash=_HASH,
            hmac_secret=_SECRET,
            now=later,
        )


def test_issue_rejects_past_expiry_and_empty_scope():
    past = datetime.now(timezone.utc) - timedelta(seconds=5)
    with pytest.raises(IsolationRejected, match="future"):
        _issue(expires_at=past)
    with pytest.raises(IsolationRejected, match="scope"):
        _issue(scope=frozenset())


def test_tampered_binding_fails_mac():
    cap = _issue()
    object.__setattr__(cap, "_audience", "cloudflare-isolate")
    with pytest.raises(IsolationRejected, match="signature"):
        verify_isolation_capability(
            cap,
            audience="cloudflare-isolate",
            tool_id="true",
            plan_hash=_HASH,
            snapshot_hash=_HASH,
            hmac_secret=_SECRET,
        )


def test_capability_fields_are_immutable():
    cap = _issue()
    with pytest.raises(IsolationRejected, match="immutable"):
        cap.audience = "other"  # type: ignore[misc]
