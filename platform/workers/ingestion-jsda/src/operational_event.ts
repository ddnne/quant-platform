export interface OperationalEvent {
  event: string;
  worker: string;
  run_id: string | null;
  job_id: string | null;
  segment_id: string | null;
  dataset: string | null;
  generation: string | null;
  cursor: number | null;
  deployment_version: string | null;
  result: string | null;
  reason: string | null;
}

export function deploymentVersion(
  meta: WorkerVersionMetadata | undefined,
): string | null {
  if (meta === undefined) return null;
  return meta.id || meta.tag || null;
}

export function operationalEvent(
  env: { CF_VERSION_METADATA?: WorkerVersionMetadata },
  event: string,
  fields: {
    run_id?: string | null;
    job_id?: string | null;
    segment_id?: string | null;
    dataset?: string | null;
    generation?: string | null;
    cursor?: number | null;
    result?: string | null;
    reason?: string | null;
  } = {},
): OperationalEvent {
  return {
    event,
    worker: "ingestion-jsda",
    run_id: fields.run_id ?? null,
    job_id: fields.job_id ?? null,
    segment_id: fields.segment_id ?? null,
    dataset: fields.dataset ?? null,
    generation: fields.generation ?? null,
    cursor: fields.cursor ?? null,
    deployment_version: deploymentVersion(env.CF_VERSION_METADATA),
    result: fields.result ?? null,
    reason: fields.reason ?? null,
  };
}

export function logOperationalEvent(
  env: { CF_VERSION_METADATA?: WorkerVersionMetadata },
  event: string,
  fields: Parameters<typeof operationalEvent>[2] = {},
): void {
  console.error(JSON.stringify(operationalEvent(env, event, fields)));
}
