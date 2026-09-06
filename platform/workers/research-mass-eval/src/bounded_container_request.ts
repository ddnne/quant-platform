/// <reference types="@cloudflare/workers-types" />

/**
 * Per-request abort bound for Container HTTP and cleanup awaits that can pin
 * the serial Durable Object callback. Ordinary resume retries start at 5s and
 * cap at 60s; 4s stays under the initial interval with 1s of scheduler slack
 * so a hung request cannot occupy the isolate through the next poll or the
 * same-generation watchdog. It does not raise the 180m outer lifecycle window
 * or the lease TTL.
 */
export const CONTROLLED_CONTAINER_REQUEST_DEADLINE_MS = 4_000;

export function containerRequestTimeoutError(): Error {
  const error = new Error("container request timeout");
  error.name = "AbortError";
  return error;
}

export function isContainerRequestTimeout(error: unknown): boolean {
  return error instanceof Error && (
    error.name === "AbortError" || /timeout/i.test(error.message)
  );
}

export async function withRequestDeadline<T>(
  work: (signal: AbortSignal) => Promise<T>,
  deadlineMs = CONTROLLED_CONTAINER_REQUEST_DEADLINE_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), deadlineMs);
  try {
    return await work(controller.signal);
  } catch (error) {
    if (controller.signal.aborted) throw containerRequestTimeoutError();
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

export async function awaitUntilAborted<T>(
  work: Promise<T>,
  signal: AbortSignal,
): Promise<T> {
  if (signal.aborted) {
    void work.then(() => undefined, () => undefined);
    throw containerRequestTimeoutError();
  }
  return await new Promise<T>((resolve, reject) => {
    let settled = false;
    const settle = (callback: () => void) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", onAbort);
      callback();
    };
    const onAbort = () => {
      void work.then(() => undefined, () => undefined);
      settle(() => reject(containerRequestTimeoutError()));
    };
    signal.addEventListener("abort", onAbort, { once: true });
    work.then(
      (value) => settle(() => resolve(value)),
      (error) => settle(() => reject(error)),
    );
  });
}

function cancelResponseBody(response: Response): void {
  const body = response.body;
  if (!body) return;
  void body.cancel("container request timeout").then(() => undefined, () => undefined);
}

export async function readAbortedBytes(
  response: Response,
  signal: AbortSignal,
  maxBytes?: number,
): Promise<Uint8Array> {
  if (response.body == null) {
    if (signal.aborted) throw containerRequestTimeoutError();
    return new Uint8Array();
  }
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let received = 0;
  const cancelReader = () => {
    void reader.cancel("container request timeout").then(() => undefined, () => undefined);
  };
  return await new Promise<Uint8Array>((resolve, reject) => {
    let settled = false;
    const settle = (callback: () => void) => {
      if (settled) return;
      settled = true;
      signal.removeEventListener("abort", onAbort);
      callback();
    };
    const onAbort = () => {
      cancelReader();
      settle(() => reject(containerRequestTimeoutError()));
    };
    if (signal.aborted) {
      onAbort();
      return;
    }
    signal.addEventListener("abort", onAbort, { once: true });
    const pump = (): void => {
      reader.read().then(
        (step) => {
          if (settled) return;
          if (signal.aborted) {
            onAbort();
            return;
          }
          if (step.done) {
            const bytes = new Uint8Array(received);
            let offset = 0;
            for (const chunk of chunks) {
              bytes.set(chunk, offset);
              offset += chunk.byteLength;
            }
            settle(() => resolve(bytes));
            return;
          }
          received += step.value.byteLength;
          if (maxBytes !== undefined && received > maxBytes) {
            cancelReader();
            settle(() => reject(new Error("container response exceeds the bound")));
            return;
          }
          chunks.push(step.value);
          pump();
        },
        (error) => {
          if (settled) return;
          if (signal.aborted) {
            onAbort();
            return;
          }
          settle(() => reject(error));
        },
      );
    };
    pump();
  });
}

export async function withContainerFetch<T>(
  target: { fetch(input: Request): Promise<Response> },
  request: Request,
  work: (response: Response, signal: AbortSignal) => Promise<T>,
  deadlineMs = CONTROLLED_CONTAINER_REQUEST_DEADLINE_MS,
): Promise<T> {
  return await withRequestDeadline(async (signal) => {
    const pending = target.fetch(new Request(request, { signal }));
    try {
      const response = await awaitUntilAborted(pending, signal);
      try {
        return await work(response, signal);
      } finally {
        cancelResponseBody(response);
      }
    } catch (error) {
      void pending.then((response) => {
        cancelResponseBody(response);
      }, () => undefined);
      throw error;
    }
  }, deadlineMs);
}

export async function fetchContainerBytes(
  target: { fetch(input: Request): Promise<Response> },
  request: Request,
  options?: { deadlineMs?: number; maxBytes?: number },
): Promise<{ status: number; headers: Headers; bytes: Uint8Array }> {
  return await withContainerFetch(
    target,
    request,
    async (response, signal) => ({
      status: response.status,
      headers: response.headers,
      bytes: await readAbortedBytes(response, signal, options?.maxBytes),
    }),
    options?.deadlineMs,
  );
}
