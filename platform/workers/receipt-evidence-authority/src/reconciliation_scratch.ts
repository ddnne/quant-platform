import { canonicalJson } from "./canonical";
import type { CanonicalStructuredRow } from "./product_materialization";

// Temporary SQL workspace inside the existing authority DO, never a history
// store. Integration must release an operation only after R2 byte verification
// and retain the raw R2 capture as the source for reconstruction.
export class ReconciliationScratch {
  constructor(
    private readonly storage: DurableObjectStorage,
    private readonly maxDatabaseBytes: number,
  ) {
    if (!Number.isSafeInteger(maxDatabaseBytes) || maxDatabaseBytes <= 0) {
      throw new Error("reconciliation scratch requires a finite byte limit");
    }
    storage.sql.exec(`CREATE TABLE IF NOT EXISTS reconciliation_scratch (
      operation_id TEXT NOT NULL,
      natural_key TEXT NOT NULL,
      row_json TEXT NOT NULL,
      PRIMARY KEY(operation_id,natural_key)
    )`);
  }

  append(operationId: string, rows: CanonicalStructuredRow[]): void {
    // Consume SQL cursors before yielding to R2 or other external I/O. A
    // transaction rolls back both conflicting replay and capacity overflow.
    this.storage.transactionSync(() => {
      this.requireCapacity();
      for (const row of rows) {
        const body = canonicalJson(row);
        this.storage.sql.exec(
          `INSERT OR IGNORE INTO reconciliation_scratch
           (operation_id,natural_key,row_json) VALUES (?,?,?)`,
          operationId, row.natural_key, body,
        );
        const stored = this.storage.sql.exec<{ row_json: string }>(
          `SELECT row_json FROM reconciliation_scratch
           WHERE operation_id=? AND natural_key=?`,
          operationId, row.natural_key,
        ).one();
        if (stored.row_json !== body) {
          throw new Error("scratch replay differs from canonical raw normalization");
        }
      }
      this.requireCapacity();
    });
  }

  count(operationId: string): number {
    return this.storage.sql.exec<{ n: number }>(
      "SELECT COUNT(*) AS n FROM reconciliation_scratch WHERE operation_id=?",
      operationId,
    ).one().n;
  }

  page(operationId: string, after: string): CanonicalStructuredRow[] {
    const rows = this.storage.sql.exec<{ row_json: string }>(
      `SELECT row_json FROM reconciliation_scratch
       WHERE operation_id=? AND natural_key>? ORDER BY natural_key LIMIT 50`,
      operationId, after,
    ).toArray();
    // Only append() writes this private table; callers never supply persisted
    // JSON. It contains the canonical normalized row, including row_digest.
    return rows.map((row) => JSON.parse(row.row_json) as CanonicalStructuredRow);
  }

  release(operationId: string): void {
    this.storage.sql.exec(
      "DELETE FROM reconciliation_scratch WHERE operation_id=?", operationId,
    );
  }

  private requireCapacity(): void {
    if (this.storage.sql.databaseSize > this.maxDatabaseBytes) {
      throw new Error("reconciliation scratch capacity exceeded");
    }
  }
}
