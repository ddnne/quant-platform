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
| `PREPARED` | environment, exact D1 resource, prior cursor and live inode/content identity, runtime source SHA, tool-binding digest, policy digest | delete only the exact candidate, if present, after proving the live file is unchanged |
| `ACQUIRED` | prior evidence plus the content-addressed export digest and format | roll back the candidate; reacquire because the in-process acquisition capability is not replayable |
| `TEMP_APPLIED` | exact local reconciliation reached the signing boundary | roll back; an unsigned or not-yet-persisted candidate is never promoted |
| `SIGNED_AUDIT` | signed candidate sync identity and closed result | roll back; storage checkpoint and file durability are not yet proven |
| `FILE_FSYNCED` | exact candidate inode/content identity after close, signature re-verification, and file fsync | atomically replace the unchanged live inode, or finish the directory fsync when replacement already occurred |
| `COMMITTED` | exact live identity after replacement and directory fsync | return an idempotent result for the prior cursor, or clear the receipt before a new sync at the committed cursor |

Every journal update is closed canonical JSON, self-digested, written through
an `O_EXCL` temporary file, file-fsynced, atomically renamed, and followed by a
parent-directory fsync. A stable `flock` serializes recovery and acquisition.
The final handoff is `os.replace(candidate, live)` followed by a parent-
directory fsync and a durable `COMMITTED` receipt. SQLite WAL/SHM/journal
sidecars are forbidden at both live handoff boundaries.

Recovery is intentionally fail-closed. It rejects stale unfinished journals
and any environment, D1 resource, prior cursor, source bundle, Wrangler
toolchain, policy, export, live mirror, or candidate identity mismatch.
`COMMITTED` is an identity-checked replay receipt rather than unfinished work,
so it may be cleaned after the normal operation lease. Do not delete or edit
the journal manually. Retry the same `sync_now` request with the original
`expected_applied_cursor`; the authority either rolls back an early candidate
and reacquires, or finishes one exact `FILE_FSYNCED` replacement. An ambiguous
identity requires forensic preservation and administrator review.

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
