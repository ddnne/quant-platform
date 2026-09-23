export function r2DatasetSegment(dataset: string): string {
  return dataset.replace(/[^A-Za-z0-9_.-]/g, "_");
}

export function r2DateSegment(eventTime: string | undefined | null): string {
  if (eventTime && typeof eventTime === "string") {
    const m = /^(\d{4}-\d{2}-\d{2})/.exec(eventTime);
    if (m) return m[1];
  }
  return "0000-01-01";
}
