# D1 mirror atomic-sync recovery

`d1_sync:sync_now` never applies a remote export to the live governed SQLite
file. The authority measures the live inode and bytes read-only, creates a
mode-`0600` candidate with `O_EXCL` in the same directory, and performs all
schema work, remote reconciliation, signed-audit persistence, checkpointing,
and verification on that candidate. The old live inode remains in place until
the candidate is closed and fsynced.

The adjacent protected journal has these durable phases:

| Phase | Durable evidence | Restart action |
| --- | --- | --- |
| `PREPARED` | environment, exact D1 resource, prior cursor and live inode/content identity, runtime source SHA, tool-binding digest, policy digest, and exact outer request identity | delete only the exact candidate, if present, after proving the live file is unchanged |
| `ACQUIRED` | prior evidence plus the content-addressed export digest and format | roll back the candidate; reacquire because the in-process acquisition capability is not replayable |
| `TEMP_APPLIED` | exact local reconciliation reached the signing boundary | roll back; an unsigned or not-yet-persisted candidate is never promoted |
| `SIGNED_AUDIT` | signed candidate sync identity, closed result, and exact outer result digest | roll back; storage checkpoint and file durability are not yet proven |
| `FILE_FSYNCED` | exact candidate inode/content identity after close, signature re-verification, and file fsync | atomically replace the unchanged live inode, or finish the directory fsync when replacement already occurred |
| `COMMITTED` | exact live identity after replacement and directory fsync | replay only to the exact original request, or clear the receipt only after its exact request/result event is visible in the append-only outer ledger |

Every journal update is closed canonical JSON and self-digested. Initial
`PREPARED` publication never writes the canonical pathname directly: a
protocol-reserved `O_EXCL` staging inode is file-fsynced and directory-fsynced,
hard-linked create-only to the canonical name, directory-fsynced, then
unlinked and directory-fsynced again. Recovery can discard a torn unpublished
staging inode (no candidate exists yet), publish a valid staging inode, or
collapse the exact two-link intermediate state. Later phase updates use an
`O_EXCL` temporary file, file fsync, atomic rename, and directory fsync. A
stable `flock` serializes recovery and acquisition.

The final handoff is `os.replace(candidate, live)` followed by a parent-
directory fsync and a durable `COMMITTED` receipt. Immediately before both a
normal replace and a recovery replace, the authority remeasures the activated
runtime bundle, Node/Wrangler resources, public-key registry-derived policy,
and server-minted processing deadline. Any observed drift or expired lease
rejects that invocation without replacing the live file. SQLite
WAL/SHM/journal directory entries are forbidden at both live handoff
boundaries; `lstat` is used so dangling sidecar symlinks also fail closed.

Recovery is intentionally fail-closed. It rejects stale unfinished journals
and any environment, D1 resource, prior cursor, source bundle, Wrangler
toolchain, policy, export, live mirror, or candidate identity mismatch.
`COMMITTED` is an identity-checked cross-store replay receipt rather than
unfinished work. A later cursor is not an acknowledgement: the receipt remains
until the append-only `SQLiteAuthorityEventLedger` proves the exact original
request id, caller, operation, purpose, request digest, and result digest were
committed. Before that proof, only the exact original request may replay the
result; every different request is rejected without cleanup. Do not delete or
edit the journal manually. Retry the same `sync_now` request with the original
`expected_applied_cursor`; the authority either rolls back an early candidate
and reacquires, finishes one exact `FILE_FSYNCED` replacement, or replays its
durable result so the outer event can commit. An ambiguous identity requires
forensic preservation and administrator review.

The runtime source SHA is the root-audited immutable authority-bundle digest.
The tool digest covers the activation-audited Node, Wrangler tree/entrypoint,
config, and lockfile resource bindings. The policy digest additionally binds
the environment-specific D1 identity, signed-key registry, canonical table
inventory, page bounds, and journal contract.

This closes the source-level crash-atomic mirror handoff only. It does not make
an authority ACTIVE, mark an operational P0 finding FIXED, publish READY, or
authorize Controlled Pilot. Those remain behind the strict finding-ledger,
key-registration, deployment, projection, B0/B4, cursor, and human-approval
gates.
