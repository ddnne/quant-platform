/** Canonical fallback pricing used only when the provider reports token usage without cost. */

import pricingPolicyDocument from "../../../../specs/policy/ai_gateway_pricing_policy.json";

const policy = pricingPolicyDocument.policy;

export const AI_GATEWAY_PRICING_POLICY_ID = policy.policy_id;
/** SHA-256 of RFC8785-equivalent canonical JSON for the nested `policy` object. */
export const AI_GATEWAY_PRICING_POLICY_DIGEST = pricingPolicyDocument.policy_digest;

export function estimateCostUsd(
  model: string,
  inputTokens: number,
  outputTokens: number,
): number {
  const rate = policy.model_rates.find((entry) => entry.model === model);
  if (!rate) throw new Error(`pricing_policy_model_missing:${model}`);
  return Number(
    (
      (inputTokens / 1_000_000) * rate.input_usd_per_million_tokens +
      (outputTokens / 1_000_000) * rate.output_usd_per_million_tokens
    ).toFixed(8),
  );
}
