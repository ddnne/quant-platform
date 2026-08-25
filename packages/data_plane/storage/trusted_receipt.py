"""No receipt-minting API lives in the storage plane.

Signed COMPLETE receipts are created only inside
``ingestion.runtime_authority._GovernedReceiptService`` after that service has
replayed immutable acquisition evidence, reread the exact structured segment,
and derived every signed claim.  Keeping this compatibility module empty makes
old imports fail closed while historical receipt rows remain auditable.
"""

from __future__ import annotations

__all__: list[str] = []
