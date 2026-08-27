# Local authority staged canary

Status: external-anchor protocol and collector are SOURCE-READY;
operational execution remains HOLD.

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
and also marks the Controlled WAL-quiescence source as not operationally
accepted.

Journal schema v4 retains every challenge, resource snapshot, lease identity,
boot identity, deadline, and acquisition time in an immutable per-attempt row.
A canonical full-attempt digest binds all of those fields into the event chain;
explicit `BEFORE INSERT` collision triggers reject `OR REPLACE` and UPSERT as
well as ordinary duplicate inserts. Therefore `plan` and `audit` report
`historical_attempt_evidence_complete:true`. `audit` also emits a canonical
`local-authority-staged-canary-anchor-candidate/v3` containing the journal
instance, exact environment set, event count,
tail sequence and digest, attempt count and full-attempt-set digest, and the
complete run-state digest. It also generates and persists one CSPRNG journal
instance identifier only while initializing a brand-new journal. Validation and
every candidate input are read from
one explicit SQLite transaction snapshot. This closes the local
audit-fidelity prerequisite; it is not an external anchor or an authorization
to execute the canary. A pre-v4 journal fails schema validation and must be
quarantined under the trusted-root recovery process rather than upgraded in
place.

The manager exposes `plan`, `audit`, a root-only `initialize-journal`, and a
fail-closed `run` surface. `initialize-journal` has no selectors and only
creates or validates the fixed empty v4 journal; it cannot dispatch a canary or
an authority operation and always reports `research_eligible:false` and HOLD.
Public
`run` and the public Python `run_canary` callable always reject with
`operational HOLD`; they cannot acquire a lease, execute an authority, or
create a journal. Every declared authority names the absent external anchor;
Controlled additionally names the quiescence transition as source-ready but
not operationally accepted. The former lease/start/execute/commit
implementation is intentionally absent rather than retained as unreachable
production code. A reviewed executable workflow must be introduced only after
both applicable blockers have real authorities and tests. Audit opens
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

The source-side external-anchor protocol is frozen by
`local-authority-anchor-protocol.schema.json`,
`local-authority-anchor-deployment.json`,
`local-authority-anchor-public-keys.json`, and
`scripts/local_authority_anchor_protocol.py`. The authority issues an
Ed25519-signed fresh challenge bound to the CSPRNG journal instance, exact
`production,staging` environment set, candidate digest, request nonce, expiry,
next monotonic generation and exact prior accepted-anchor digest. The collector
signs a closed canonical commit request containing the manager-rederived
candidate plus a closed lineage proof. On the first commit that proof contains
the complete canonical event chain, attempts, and runs. Later commits contain
only the exact event suffix, newly introduced immutable attempt records, and
new or changed secret-free run projections relative to the remotely retained
prefix/state. The authority merges those deltas into its retained state,
independently rehashes the suffix, requires every new attempt and run to have
its exact lease lineage, rederives the complete attempt-set and run-state
digests, keeps terminal runs immutable, and admits nonterminal changes only
when the suffix proves the corresponding transition. It retains the accepted
event, attempt, and run snapshots as part of its compare-and-swap state. The authority
atomically compares generation and prior digest, rejects replay, rollback,
journal substitution and higher-height as well as same-height forks, persists
the accepted high water, and returns an Ed25519-signed receipt binding the exact
challenge, request, lineage proof and candidate. No public collector input
supplies a `go`, count, tail, set digest, run-state digest, generation or prior
digest.

The lineage proof detects divergence from bytes previously accepted by the
remote authority. It does not carry the original service signatures, archived
challenge JSON, resource JSON, or result JSON, so the remote does not
independently establish the provenance of those underlying authority
operations. Their validation remains a responsibility of the trusted local
root manager before projection. Do not describe the anchor receipt alone as a
proof that each authority signature was valid.

The reference authority state machine is an executable protocol model, not a
provider adapter or deployment. The checked-in deployment remains
`PENDING_PROVIDER_SELECTION`; endpoint and client/remote keys are `null`, the
independently digest-pinned public-key registry is `PENDING` with zero keys, and
external administrator separation is unverified. No provider, account or
credential is inferred. `collect` therefore fails before reading the journal,
root config or network.

The current source intentionally does not claim key-rotation support. The
remote registry admits exactly one active remote verification key, and local
audit replay uses the current client key. Replacing either key after the first
accepted generation makes historical replay fail closed. An initial provider
activation must therefore treat both keys as immutable and retain them for the
full lifetime of every audit record. Production rotation or compromise
recovery is an additional blocker: implement and independently review pinned
remote and client verification-key histories (one active signing key plus
retained verify-only keys) before rotating. `plan` reports
`HISTORICAL_KEY_REGISTRIES_NOT_IMPLEMENTED` and does not hide this limitation.

After a future reviewed provider choice, the collector accepts only the fixed
root-owned config path and exact endpoint/key identities already pinned by the
activated deployment manifest. Transport is TLS HTTPS with a five-second
timeout on each blocking I/O operation and a bounded body size; it does not
claim one total wall-clock deadline. Redirects are rejected and ambient
proxies, cookies and credentials are disabled. The complete local reverify,
submission, remote challenge/commit/resolve, and receipt-or-abandonment append
is serialized by one nonblocking `flock` on a descriptor-pinned, root-owned,
mode-0600, single-link file in the fixed audit directory. A second process
fails before any remote RPC or new submission, and a forked child cannot reuse
the parent's lock ownership. Before sending a commit, the
collector fsyncs a mode-0600 create-only submission record with a monotonic
attempt ordinal. If the response is lost, the pinned `/resolve` operation
atomically returns either the already accepted receipt or an Ed25519-signed
`NOT_ACCEPTED` decision that permanently abandons that exact commit at the
remote authority. The collector fsyncs the negative decision as a create-only
abandonment record before issuing a fresh challenge at the same generation.
This closes both accepted-response-loss and never-received/expired-challenge
restart paths without late-accepting an expired request. Each verified receipt
and its complete wire lineage is likewise stored as one root-owned mode-0600
create-only record below the fixed mode-0700 local audit directory, fsynced,
reread and signature-verified. That local audit improves recovery but is not
itself rollback evidence; the remote compare-and-swap state remains
authoritative.

The local root administrator must not hold the anchor control-plane credentials
or deletion capability. Merely copying `journal.sqlite3`, its hash, an anchor
receipt, or audit JSON to another root-writable path does not meet this
requirement.

Controlled's product writer normally uses WAL, while its canary audit requires
a sidecar-free DELETE-mode database. Before Controlled can enter this ceremony,
source now provides one authority-owned transition boundary. The Controlled
daemon acquires a service-owned lifecycle lock before `build_service` or any
product SQLite open and retains it for its process lifetime. The transition,
running as that same UID and deriving its store only from the protected
activation, acquires the lock exclusively, pins the existing mode-0600
single-link database inode, durably creates a restart-forbidden marker, obtains
SQLite exclusive locking, requires `wal_checkpoint(TRUNCATE)` to return exactly
`(0,0,0)`, switches to exact DELETE mode, closes SQLite, fsyncs the database and
parent directory, and requires WAL, SHM, and rollback sidecars to be absent.
It never unlinks a SQLite sidecar: a retained sidecar or any partial failure
leaves the marker in place and the daemon refuses to resume.

The retained same-inode session exposes an explicit WAL-restore method, but it
is structurally fail-closed until an externally anchored bounded-completion
verifier is wired; a same-UID Python object or caller digest is not accepted as
a completion capability. Consequently there is no public transition/restore
CLI, the source has not been exercised under the six distinct real service
principals, and no operational completion claim is made. Root deleting
sidecars, copying the main file, removing the marker, or changing
`journal_mode` while a writer can still run remains forbidden. Controlled's
blocker is `SOURCE_READY_NOT_OPERATIONALLY_ACCEPTED`, and its operational
canary remains HOLD.

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

sudo /PROTECTED/PYTHON -I \
  /PROTECTED/BUNDLE/scripts/manage_local_authority_staged_canary.py \
  initialize-journal
```

The external-anchor surface itself has no selectors:

```sh
python scripts/manage_local_authority_anchor.py plan
sudo /PROTECTED/PYTHON -I \
  /PROTECTED/BUNDLE/scripts/manage_local_authority_anchor.py collect
```

`plan` reports `SOURCE_READY` and `operational_state:HOLD`. `collect` currently
exits nonzero without network activity because provider selection, remote
resource provisioning, independent administrator acceptance, an active pinned
key registry, fixed root config and client key are absent. Activation is a
separately reviewed operational change. Even after a first accepted anchor,
`run_canary` remains HOLD until a reviewed PR restores a bounded executable
workflow and Controlled's quiescence transition exists. An anchor receipt is
not a release, READY, Receipt COMPLETE, Pilot, or Mass authorization.

Do not mark A2 FIXED from a canary. Independent review must still verify all
seven authority protocols and update the pinned finding ledger in a normal
reviewed commit. Human presence and authenticated provenance remain mandatory
for the Trader authorization smoke, Receipt remains on its separate Cloudflare
activation runbook, and the external journal high-water anchor remains an
operational prerequisite.
