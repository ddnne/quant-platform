import {
  PILOT_BUDGET_CAPS,
  cancelPreProviderReservation,
  finalizeOwnedPaperReservation,
  queryOwnedBudget,
  reserveOwnedBudget,
  type BudgetStorage,
} from "./budget_do";

const CONTROLLED_AMOUNTS = {
  experiment_plans: PILOT_BUDGET_CAPS.max_experiment_plans,
  generations: PILOT_BUDGET_CAPS.max_generations,
  paper_runs: 4,
  model_calls: 0,
  input_tokens: 0,
  output_tokens: 0,
  cached_tokens: 0,
  cost_usd: 0,
} as const;

export type ControlledPaperBudgetInput = {
  idempotency_key: string;
  request_digest: string;
  reserve_owner_capability: string;
};

export async function reserveControlledPaper(
  storage: BudgetStorage,
  input: ControlledPaperBudgetInput,
) {
  return reserveOwnedBudget(storage, {
    idempotency_key: input.idempotency_key,
    request_digest: input.request_digest,
    reserve_owner_capability: input.reserve_owner_capability,
    amounts: { ...CONTROLLED_AMOUNTS },
    acquire_lease: true,
  });
}

export async function finalizeControlledPaper(
  storage: BudgetStorage,
  input: ControlledPaperBudgetInput & { lease_id: string },
) {
  return finalizeOwnedPaperReservation(storage, {
    idempotency_key: input.idempotency_key,
    request_digest: input.request_digest,
    reserve_owner_capability: input.reserve_owner_capability,
    lease_id: input.lease_id,
  });
}

export async function cancelControlledPaper(
  storage: BudgetStorage,
  input: ControlledPaperBudgetInput,
) {
  return cancelPreProviderReservation(storage, {
    idempotency_key: input.idempotency_key,
    request_digest: input.request_digest,
    reserve_owner_capability: input.reserve_owner_capability,
  });
}

export async function queryControlledPaper(
  storage: BudgetStorage,
  input: ControlledPaperBudgetInput,
) {
  return queryOwnedBudget(storage, {
    idempotency_key: input.idempotency_key,
    request_digest: input.request_digest,
    reserve_owner_capability: input.reserve_owner_capability,
  });
}

export const CONTROLLED_PAPER_BUDGET_AMOUNTS = CONTROLLED_AMOUNTS;
