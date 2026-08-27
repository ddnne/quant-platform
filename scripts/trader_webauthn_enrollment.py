#!/usr/bin/env python3
"""Print non-activating Trader WebAuthn request/proposal JSON to stdout.

The CLI never writes an activation file and never requests or accepts private
credential material.  It does durably record expiring one-use challenges in
the explicitly selected enrollment ledger.  Between ``request`` and
``propose-activation`` an operator must run the indicated browser/OS WebAuthn
creation prompt with human presence and save its raw registration response.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parents[1]
_PRODUCT = _ROOT / "packages" / "product"
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
if str(_PRODUCT) not in sys.path:
    sys.path.insert(0, str(_PRODUCT))

from execution.trader_webauthn_authority_v2 import (  # noqa: E402
    ExactFourTraderRelyingPartyV2,
)
from execution.trader_webauthn_enrollment_v2 import (  # noqa: E402
    TraderWebAuthnEnrollmentV2Error,
    build_trader_root_activation_proposal_v2,
    build_trader_webauthn_enrollment_request_v2,
)


def _timestamp(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an explicit timezone")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate public Trader WebAuthn ceremony and root-review proposals; "
            "never exports a credential private key or installs activation state."
        )
    )
    commands = parser.add_subparsers(dest="command", required=True)
    request = commands.add_parser(
        "request",
        help="print browser/OS human-presence ceremony parameters",
    )
    request.add_argument("--environment", choices=("staging", "production"), required=True)
    request.add_argument("--policy-id", required=True)
    request.add_argument("--policy-generation", type=int, required=True)
    request.add_argument("--rp-id", required=True)
    request.add_argument("--origin", required=True)
    request.add_argument("--rp-effective-at", required=True)
    request.add_argument(
        "--counter-mode", choices=("COUNTING", "COUNTERLESS"), required=True
    )
    request.add_argument("--enrollment-ledger", type=Path, required=True)
    request.add_argument("--ttl-seconds", type=int, default=300)
    request.add_argument("--created-at")

    proposal = commands.add_parser(
        "propose-activation",
        help="verify a raw registration response and print a root-review proposal",
    )
    proposal.add_argument("--request-json", type=Path, required=True)
    proposal.add_argument("--registration-response-json", type=Path, required=True)
    proposal.add_argument("--enrollment-ledger", type=Path, required=True)
    proposal.add_argument("--service-uid", type=int, required=True)
    proposal.add_argument("--controlled-execution-uid", type=int, required=True)
    proposal.add_argument("--controlled-execution-socket", type=Path, required=True)
    proposal.add_argument("--store-path", type=Path, required=True)
    proposal.add_argument("--generated-at")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "request":
            rp = ExactFourTraderRelyingPartyV2(
                environment=args.environment,
                policy_id=args.policy_id,
                policy_generation=args.policy_generation,
                rp_id=args.rp_id,
                origin=args.origin,
                effective_at=args.rp_effective_at,
            )
            result = build_trader_webauthn_enrollment_request_v2(
                environment=args.environment,
                relying_party=rp,
                counter_mode=args.counter_mode,
                enrollment_ledger_path=args.enrollment_ledger,
                created_at=_timestamp(args.created_at),
                ttl_seconds=args.ttl_seconds,
            )
        else:
            result = build_trader_root_activation_proposal_v2(
                args.request_json.read_bytes(),
                args.registration_response_json.read_bytes(),
                enrollment_ledger_path=args.enrollment_ledger,
                service_uid=args.service_uid,
                controlled_execution_uid=args.controlled_execution_uid,
                controlled_execution_socket_path=(
                    args.controlled_execution_socket
                ),
                store_path=args.store_path,
                generated_at=_timestamp(args.generated_at),
            )
    except (OSError, TypeError, ValueError, TraderWebAuthnEnrollmentV2Error) as exc:
        print(f"Trader enrollment proposal rejected: {exc}", file=sys.stderr)
        return 2
    sys.stdout.buffer.write(result + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
