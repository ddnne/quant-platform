# Local authority staged canary

Status: source contract implemented; operational execution remains pending.

This source defines research-ineligible diagnostics for five signed local OS
authorities. It does not break or close A2 by itself. The
ordinary pinned finding-ledger gate remains the only route to ACTIVE product
operations, READY publication, a COMPLETE receipt, Controlled Pilot, or Mass.
Operational use is NO-GO until a separately reviewed external signed or
append-only high-water anchor makes attempt rollback detectable.

## Frozen boundary

`specs/authorities/local-authority-staged-canary-policy.json` is independently
digest-pinned by code. It fixes each authority, environment, action, proof kind,
resource role, canonical journal, lease length, retry count, and source-SHA
binding. The exact SHA is never supplied to the command: it comes from the
root-owned, content-addressed runtime-bundle manifest created by the existing
bootstrap. Runtime config paths likewise come only from the root-owned config
and the principal manifest. The protected runtime archive excludes `tests/`,
including the test-only closure-reflection harness.

The journal is always:

```text
/Library/Application Support/quant-platform/authorities/staged-canary/journal.sqlite3
```

It must be a root-owned mode-0600 regular file below a root-owned mode-0700
directory. No CLI or library production workflow accepts an alternate path,
owner, UID, source SHA, resource digest, action, or completion digest.

After its first complete schema/meta initialization, this journal is crash- and
power-loss-durable, not privileged-rollback-evident. A crash during the initial
empty-file creation remains fail-closed and requires trusted-root quarantine
and reinitialization before any canary attempt exists.
The trusted human root administrator can replace or restore the root-owned
SQLite file and can access service-owned key material. That administrator is
therefore inside this diagnostic's trust boundary. `plan` and `audit` report
`trusted_root_required:true`, `privileged_rollback_evident:false`, and
`durability_scope:POST_INITIALIZATION_CRASH_AND_POWER_LOSS_ONLY`. A same-file
hash chain cannot upgrade that assurance; an external high-water anchor is
required before any operational ceremony.

Retries retain a contiguous hash-chained event history and the latest complete
challenge/resource snapshot, but the current schema overwrites prior attempt
snapshots. It therefore reports `historical_attempt_evidence_complete:false`.
Immutable per-attempt challenge/resource evidence is a P2 audit-fidelity
prerequisite for the future external-anchor ceremony, not evidence supplied by
this source contract.

The manager exposes only `plan`, `audit`, and an atomic `run`. `run` acquires a
durable bounded lease, rechecks its monotonic deadline under the journal write
lock, executes the exact protected runtime as the declared service UID,
validates the preflight, remeasures source/resources, rechecks the monotonic
deadline again under the write lock, and commits a hash-chained event. A crash
leaves a recoverable lease; a later run may reclaim it after the same-boot
monotonic deadline or a boot-identity change, up to three attempts.
The retry family is fixed by authority, environment, action, and source SHA;
changing resource metadata cannot reset the three-attempt bound. Audit opens
the journal with SQLite `mode=ro`. WAL headers and WAL/SHM sidecars are rejected
before SQLite opens the file. A write-side open can recover only a protected
same-directory DELETE-mode rollback journal, and must remove it before full
schema, event-chain, and state validation.

Each of the five file-backed authorities first constructs its exact inactive
handler wiring (including peer UIDs, sockets and stores) without calling a
product operation.
Controlled uses a dedicated read-only activation preflight which does not
construct its SQLite writer and therefore cannot initialize or migrate product
state. Authority event ledgers and the Controlled store are descriptor-pinned,
DELETE-mode, sidecar-free, exact-schema, immutable SQLite reads. Authorities
then sign only the closed `local-authority-staged-canary-evidence/v1` body.
Every result is
`CANARY_NOT_RESEARCH_ELIGIBLE`, `research_eligible:false`, and false at all five
strict boundaries.
Raw service-signed canary bytes are noncanonical diagnostics. Any future
consumer or external anchor must require the root manager's committed journal
chain; it must never accept a runner response by itself.

Trader is not actionable in this canary plane. Its inactive WebAuthn preflight
has no authority-held signature, so a Python/root orchestrator could otherwise
self-assert the output. Trader remains PENDING until kernel-authenticated IPC or
an authority-held attestation key proves runner provenance. The CLI rejects
Trader `plan` and `run` selectors rather than emitting unsigned evidence.

Receipt is also intentionally excluded. A local file cannot independently
prove a Cloudflare Service Binding caller or deployed version. Receipt needs a
separate typed Cloudflare canary protocol and authenticated deployment
evidence; until then it remains PENDING and caller-supplied evidence is
rejected.

## Future operator sequence

Do not execute this sequence while the external high-water anchor is absent.
The commands document the eventual interface only.

First install the reviewed exact commit as the protected runtime bundle using
the existing bootstrap. Then invoke the manager from that bundle with its
root-owned Python, not from a mutable checkout. The following module commands
show the interface; replace the paths with `runtime-bundle.json`'s protected
`python_path`, `bundle_path`, and manager file.

```sh
python scripts/manage_local_authority_staged_canary.py \
  plan --authority ready --environment staging

sudo /PROTECTED/PYTHON -I \
  /PROTECTED/BUNDLE/scripts/manage_local_authority_staged_canary.py \
  run --authority ready --environment staging

sudo /PROTECTED/PYTHON -I \
  /PROTECTED/BUNDLE/scripts/manage_local_authority_staged_canary.py audit
```

Do not mark A2 FIXED from a canary. Independent review must still verify all
seven authority protocols and update the pinned finding ledger in a normal
reviewed commit. Human presence and authenticated provenance remain mandatory
for the Trader authorization smoke, Receipt remains on its separate Cloudflare
activation runbook, and the external journal high-water anchor remains an
operational prerequisite.
