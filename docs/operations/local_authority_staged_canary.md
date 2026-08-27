# Local authority staged canary

Status: source contract implemented; operational execution remains pending.

This procedure breaks only the A2 bootstrap-evidence cycle for the six local OS
authorities. It is not a second release gate and cannot close A2 by itself. The
ordinary pinned finding-ledger gate remains the only route to ACTIVE product
operations, READY publication, a COMPLETE receipt, Controlled Pilot, or Mass.

## Frozen boundary

`specs/authorities/local-authority-staged-canary-policy.json` is independently
digest-pinned by code. It fixes each authority, environment, action, proof kind,
resource role, canonical journal, lease length, retry count, and source-SHA
binding. The exact SHA is never supplied to the command: it comes from the
root-owned, content-addressed runtime-bundle manifest created by the existing
bootstrap. Runtime config paths likewise come only from the root-owned config
and the principal manifest.

The journal is always:

```text
/Library/Application Support/quant-platform/authorities/staged-canary/journal.sqlite3
```

It must be a root-owned mode-0600 regular file below a root-owned mode-0700
directory. No CLI or library production workflow accepts an alternate path,
owner, UID, source SHA, resource digest, action, or completion digest.

The manager exposes only `plan`, `audit`, and an atomic `run`. `run` acquires a
durable bounded lease, rechecks its monotonic deadline under the journal write
lock, executes the exact protected runtime as the declared service UID,
validates the preflight, remeasures source/resources, rechecks the monotonic
deadline again under the write lock, and commits a hash-chained event. A crash
leaves a recoverable lease; a later run may reclaim it after the same-boot
monotonic deadline or a boot-identity change, up to three attempts.

File-backed authorities sign only the closed
`local-authority-staged-canary-evidence/v1` body. Trader performs an exact-UID
load of the root-owned WebAuthn registration/RP/store preflight and explicitly
does not claim a signature or a human-present authorization. Every result is
`CANARY_NOT_RESEARCH_ELIGIBLE`, `research_eligible:false`, and false at all five
strict boundaries.

Receipt is intentionally excluded. A local file cannot independently prove a
Cloudflare Service Binding caller or deployed version. Receipt needs a separate
typed Cloudflare canary protocol and authenticated deployment evidence; until
then it remains PENDING and caller-supplied evidence is rejected.

## Operator sequence

First install the reviewed exact commit as the protected runtime bundle using
the existing bootstrap. Then invoke the manager from that bundle with its
root-owned Python, not from a mutable checkout. The following module commands
show the interface; replace the paths with `runtime-bundle.json`'s protected
`python_path`, `bundle_path`, and manager file.

```sh
python -I -m scripts.manage_local_authority_staged_canary \
  plan --authority ready --environment staging

sudo /PROTECTED/PYTHON -I \
  /PROTECTED/BUNDLE/scripts/manage_local_authority_staged_canary.py \
  run --authority ready --environment staging

sudo /PROTECTED/PYTHON -I \
  /PROTECTED/BUNDLE/scripts/manage_local_authority_staged_canary.py audit
```

Do not mark A2 FIXED from a canary. Independent review must still verify all
seven authority protocols and update the pinned finding ledger in a normal
reviewed commit. Human presence remains mandatory for the Trader authorization
smoke, and Receipt remains on its separate Cloudflare activation runbook.
