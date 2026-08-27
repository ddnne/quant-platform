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
and the principal manifest. The protected runtime archive excludes `tests/`.

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
required before any operational ceremony. The machine-readable plan/audit
therefore remains `operational_state:HOLD`, names the absent external anchor,
and also names the missing WAL-quiescence transition for Controlled.

Journal schema v3 retains every challenge, resource snapshot, lease identity,
boot identity, deadline, and acquisition time in an immutable per-attempt row.
A canonical full-attempt digest binds all of those fields into the event chain;
explicit `BEFORE INSERT` collision triggers reject `OR REPLACE` and UPSERT as
well as ordinary duplicate inserts. Therefore `plan` and `audit` report
`historical_attempt_evidence_complete:true`. `audit` also emits a canonical
`local-authority-staged-canary-anchor-candidate/v2` containing the event count,
tail sequence and digest, attempt count and full-attempt-set digest, and the
complete run-state digest. Validation and every candidate input are read from
one explicit SQLite transaction snapshot. This closes the local
audit-fidelity prerequisite; it is not an external anchor or an authorization
to execute the canary. A pre-v3 journal fails schema validation and must be
quarantined under the trusted-root recovery process rather than upgraded in
place.

The manager exposes `plan`, `audit`, and a fail-closed `run` surface. Public
`run` and the public Python `run_canary` callable always reject with
`operational HOLD`; they cannot acquire a lease, execute an authority, or
create a journal. Every declared authority names the absent external anchor;
Controlled additionally names the missing quiescence transition. The former
lease/start/execute/commit implementation is intentionally absent rather than
retained as unreachable production code. A reviewed executable workflow must
be introduced only after both applicable blockers have real authorities and
tests. Audit opens
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

The external anchor must issue a fresh journal-instance and environment-set
bound challenge, enforce a monotonic generation and exact prior-anchor digest
with compare-and-swap,
persist the accepted candidate in an append-only or rollback-evident system,
and return a signed receipt from an independently pinned key. The local root
administrator must not hold the anchor control-plane credentials or a deletion
capability. Merely copying `journal.sqlite3`, its hash, or the audit JSON to
another root-writable path does not meet this requirement.

Controlled's product writer normally uses WAL, while its canary audit requires
a sidecar-free DELETE-mode database. Before Controlled can enter this ceremony,
a separately reviewed authority-owned transition must: stop new IPC and prove
the writer quiescent; retain the same pinned database inode; acquire an
exclusive SQLite lock as the Controlled UID; run a truncating checkpoint and
require the exact successful empty result; switch to DELETE mode; close and
fsync the database and parent directory; prove WAL, SHM, and rollback sidecars
absent; run the bounded canary; and only then resume the writer. Root deleting
sidecars, copying the main file, or changing `journal_mode` while a writer can
still run is forbidden. This transition is not yet implemented, so the
Controlled operational canary remains HOLD.

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

## Future operator interface

Do not execute a ceremony while the external high-water anchor is absent. The
commands below document the eventual interface only. In the current source the
`run` command always exits nonzero with HOLD, even when invoked as root from a
protected bundle; Controlled remains held by both blockers.

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
