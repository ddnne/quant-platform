/** Shared operation projection for pre-migration and R2-backed receipts. */
export function reconciliationRead(hasR2Measurements: boolean): { columns: string; join: string } {
  return hasR2Measurements ? {
    columns: `operation.structured_storage,
      r2.artifact_digest AS r2_artifact_digest,
      r2.row_count AS r2_row_count,
      r2.natural_key_digest AS r2_natural_key_digest,
      r2.measured_at AS r2_measured_at,
      publication.publication_seq AS r2_publication_seq,
      publication.receipt_digest AS r2_publication_receipt_digest,
      publication.artifact_digest AS r2_publication_artifact_digest,`,
    join: `LEFT JOIN receipt_r2_reconciliations r2
      ON r2.operation_id=operation.operation_id
      LEFT JOIN receipt_product_publications publication
      ON publication.operation_id=operation.operation_id`,
  } : { columns: "'legacy_d1' AS structured_storage,", join: "" };
}
