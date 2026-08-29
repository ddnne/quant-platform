import {
  PERSONAL_RESEARCH_CONTAINER_NAME,
  PERSONAL_RESEARCH_RUNNER_VERSION,
} from "./personal_research_contract";
import type { Env } from "./types";

type PersonalResearchContainerStub = ReturnType<
  NonNullable<Env["PERSONAL_RESEARCH_CONTAINER"]>["getByName"]
>;

const RUNNER_READY_URL = "http://container/ready";
const MAX_RUNNER_READY_BYTES = 1024;

type RunnerIdentityProbe =
  | { state: "MATCH" }
  | { state: "MISMATCH"; service: string }
  | { state: "UNKNOWN"; reason: string };

function isExactRunnerIdentity(
  value: unknown,
): value is { ok: true; service: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    Object.keys(value).sort().join(",") === "ok,service" &&
    "ok" in value &&
    value.ok === true &&
    "service" in value &&
    typeof value.service === "string"
  );
}

function errorDetail(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

export function personalResearchContainer(
  env: Env,
): PersonalResearchContainerStub {
  if (!env.PERSONAL_RESEARCH_CONTAINER) {
    throw new Error("PERSONAL_RESEARCH_CONTAINER not bound");
  }
  return env.PERSONAL_RESEARCH_CONTAINER.getByName(
    PERSONAL_RESEARCH_CONTAINER_NAME,
  );
}

async function probeRunnerIdentity(
  target: PersonalResearchContainerStub,
): Promise<RunnerIdentityProbe> {
  let response: Response;
  try {
    response = await target.fetch(
      new Request(RUNNER_READY_URL, {
        headers: { accept: "application/json" },
      }),
    );
  } catch (error) {
    return {
      state: "UNKNOWN",
      reason: `probe failed: ${errorDetail(error)}`,
    };
  }
  if (response.status !== 200) {
    return {
      state: "UNKNOWN",
      reason: `probe returned HTTP ${response.status}`,
    };
  }
  const rawLength = response.headers.get("content-length") ?? "";
  if (
    !/^\d+$/.test(rawLength) ||
    Number(rawLength) < 1 ||
    Number(rawLength) > MAX_RUNNER_READY_BYTES
  ) {
    return { state: "UNKNOWN", reason: "probe length was not trustworthy" };
  }
  let bytes: ArrayBuffer;
  try {
    bytes = await response.arrayBuffer();
  } catch (error) {
    return {
      state: "UNKNOWN",
      reason: `probe body failed: ${errorDetail(error)}`,
    };
  }
  if (
    bytes.byteLength !== Number(rawLength) ||
    bytes.byteLength > MAX_RUNNER_READY_BYTES
  ) {
    return { state: "UNKNOWN", reason: "probe body length did not match" };
  }
  let body: unknown;
  try {
    body = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    return { state: "UNKNOWN", reason: "probe body was not valid JSON" };
  }
  if (!isExactRunnerIdentity(body)) {
    return { state: "UNKNOWN", reason: "probe body schema was not trusted" };
  }
  return body.service === PERSONAL_RESEARCH_RUNNER_VERSION
    ? { state: "MATCH" }
    : { state: "MISMATCH", service: body.service };
}

async function destroyMismatchedRunner(
  target: PersonalResearchContainerStub,
): Promise<void> {
  try {
    await target.destroy();
  } catch (error) {
    throw new Error(
      `runner identity mismatch cleanup failed: ${errorDetail(error)}`,
    );
  }
}

export async function verifiedPersonalResearchContainer(
  env: Env,
): Promise<PersonalResearchContainerStub> {
  const first = personalResearchContainer(env);
  const firstProbe = await probeRunnerIdentity(first);
  if (firstProbe.state === "MATCH") return first;
  if (firstProbe.state === "UNKNOWN") {
    throw new Error(`runner readiness unknown: ${firstProbe.reason}`);
  }

  await destroyMismatchedRunner(first);
  const replacement = personalResearchContainer(env);
  const replacementProbe = await probeRunnerIdentity(replacement);
  if (replacementProbe.state === "MATCH") return replacement;
  if (replacementProbe.state === "UNKNOWN") {
    throw new Error(
      `runner readiness reprobe unknown: ${replacementProbe.reason}`,
    );
  }

  await destroyMismatchedRunner(replacement);
  throw new Error("runner identity mismatch persisted after one replacement");
}
