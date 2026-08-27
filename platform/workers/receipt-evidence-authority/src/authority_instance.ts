import authorityInstances from "../../../../packages/data_plane/data_contracts/receipt_authority_instances.json";
import { canonicalDigest } from "./canonical";
import type { AuthorityEnvironment, JsonValue, ReceiptAuthorityEnv } from "./types";

type AuthorityInstance = {
  environment: AuthorityEnvironment;
  authority_id: "receipt-evidence-authority";
  worker_name: string;
  resources: Record<string, Record<string, string>>;
};

function instanceFor(environment: AuthorityEnvironment): AuthorityInstance {
  if (authorityInstances.schema_version !== "receipt-authority-instances/v1") {
    throw new Error("receipt authority instance contract version mismatch");
  }
  const instance = authorityInstances.instances[environment];
  if (
    instance.environment !== environment ||
    instance.authority_id !== "receipt-evidence-authority"
  ) {
    throw new Error("receipt authority instance contract is inconsistent");
  }
  return instance as AuthorityInstance;
}

/**
 * Resolve authority scope only from the deployed Worker environment binding.
 * Request bodies and reconciliation claims never choose this value.
 */
export async function authorityInstanceScope(
  env: Pick<ReceiptAuthorityEnv, "ENVIRONMENT">,
): Promise<{
  environment: AuthorityEnvironment;
  authorityInstanceDigest: string;
}> {
  const instance = instanceFor(env.ENVIRONMENT);
  return {
    environment: env.ENVIRONMENT,
    authorityInstanceDigest: await canonicalDigest(instance as unknown as JsonValue),
  };
}

export async function authorityInstanceDigest(
  environment: AuthorityEnvironment,
): Promise<string> {
  return canonicalDigest(instanceFor(environment) as unknown as JsonValue);
}
