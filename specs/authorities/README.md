# Authority contracts

This directory freezes the remaining Cloudflare protocol schemas used by
Paper-only research:

- J-Quants acquisition RPC and canonical vectors
- frozen-mirror handoff/request for D1 sync

Receipt PENDING evidence lives in `packages/data_plane/data_contracts/`
public-key registries plus
`docs/operations/receipt_evidence_authority_activation.md`. Local
six-principal OS custody, Trader WebAuthn, external-anchor, and staged canary
were removed from the working tree in Phase 6.3.2; Git history is the archive.
See [`docs/architecture/adr_phase632_architecture_simplification.md`](../../docs/architecture/adr_phase632_architecture_simplification.md).
