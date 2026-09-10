import { describe, expect, it, vi } from "vitest";

import {
  containerRequestTimeoutError,
  fetchContainerBytes,
  readAbortedBytes,
  withContainerFetch,
} from "./bounded_container_request";

function rejectWhenAborted(signal: AbortSignal): Promise<never> {
  return new Promise((_resolve, reject) => {
    const fail = () => reject(containerRequestTimeoutError());
    if (signal.aborted) {
      fail();
      return;
    }
    signal.addEventListener("abort", fail, { once: true });
  });
}

function stalledBody(): ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start() {
      // Never enqueues or closes; only abort/cancel can finish the read.
    },
    cancel() {},
  });
}

describe("bounded container requests", () => {
  it("aborts a POST whose cloned body request only rejects on abort", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let signalled = false;
    let receivedBody = "";
    let markReady: () => void;
    const fixtureReady = new Promise<void>((resolve) => {
      markReady = resolve;
    });
    const target = {
      fetch: async (request: Request) => {
        expect(request.method).toBe("POST");
        receivedBody = await request.clone().text();
        request.signal.addEventListener("abort", () => {
          signalled = true;
        }, { once: true });
        markReady();
        return await rejectWhenAborted(request.signal);
      },
    };
    try {
      const pending = fetchContainerBytes(
        target,
        new Request("http://container/v1/controlled-pilot", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: "{\"job_id\":\"job\"}",
        }),
        { deadlineMs: 25 },
      );
      const expected = expect(pending).rejects.toThrow("container request timeout");
      await fixtureReady;
      await vi.advanceTimersByTimeAsync(25);
      await expected;
      expect(receivedBody).toBe("{\"job_id\":\"job\"}");
      expect(signalled).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("aborts a fetch that only rejects when the request signal aborts", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let signalled = false;
    let heldRequest: Request | undefined;
    let markReady: () => void;
    const fixtureReady = new Promise<void>((resolve) => {
      markReady = resolve;
    });
    const target = {
      fetch: async (request: Request) => {
        heldRequest = request;
        request.signal.addEventListener("abort", () => {
          signalled = true;
        }, { once: true });
        markReady();
        return await rejectWhenAborted(request.signal);
      },
    };
    try {
      const pending = fetchContainerBytes(
        target,
        new Request("http://container/ready"),
        { deadlineMs: 25 },
      );
      const expected = expect(pending).rejects.toThrow("container request timeout");
      await fixtureReady;
      await vi.advanceTimersByTimeAsync(25);
      await expected;
      expect(signalled).toBe(true);
      expect(heldRequest?.signal.aborted).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("unblocks a fetch that ignores AbortSignal when the deadline elapses", async () => {
    let started = false;
    const target = {
      fetch: async () =>
        new Promise<Response>(() => {
          started = true;
        }),
    };
    const began = Date.now();
    await expect(
      fetchContainerBytes(
        target,
        new Request("http://container/v1/controlled-pilot", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: "{\"job_id\":\"job\"}",
        }),
        { deadlineMs: 25 },
      ),
    ).rejects.toThrow("container request timeout");
    expect(started).toBe(true);
    expect(Date.now() - began).toBeLessThan(1_000);
  });

  it("cancels a late response body after an ignore-abort fetch times out", async () => {
    let cancelled = false;
    let deliver: ((response: Response) => void) | undefined;
    const target = {
      fetch: () =>
        new Promise<Response>((resolve) => {
          deliver = resolve;
        }),
    };
    await expect(
      fetchContainerBytes(target, new Request("http://container/v1/jobs/job"), { deadlineMs: 25 }),
    ).rejects.toThrow("container request timeout");
    deliver!(
      new Response(
        new ReadableStream<Uint8Array>({
          start() {},
          cancel() {
            cancelled = true;
          },
        }),
        { status: 202 },
      ),
    );
    await Promise.resolve();
    await Promise.resolve();
    expect(cancelled).toBe(true);
  });

  it("cancels a stalled response body that never produces bytes except on abort", async () => {
    let cancelled = false;
    const target = {
      fetch: async () =>
        new Response(
          new ReadableStream<Uint8Array>({
            start() {},
            cancel() {
              cancelled = true;
            },
          }),
          { status: 202 },
        ),
    };
    await expect(
      fetchContainerBytes(target, new Request("http://container/v1/jobs/job"), { deadlineMs: 25 }),
    ).rejects.toThrow("container request timeout");
    expect(cancelled).toBe(true);
  });

  it("unblocks awaiters of a stalled body via abort without a manual release", async () => {
    const response = new Response(stalledBody(), { status: 200 });
    const controller = new AbortController();
    const pending = readAbortedBytes(response, controller.signal);
    controller.abort();
    await expect(pending).rejects.toThrow("container request timeout");
  });

  it("returns from an early-rejected response whose body.cancel never settles", async () => {
    let cancelled = false;
    const target = {
      fetch: async () =>
        new Response(
          new ReadableStream<Uint8Array>({
            start() {},
            cancel() {
              cancelled = true;
              return new Promise(() => {
                // Cancellation is initiated; the callback must not await it.
              });
            },
          }),
          { status: 503 },
        ),
    };
    const started = Date.now();
    const result = await withContainerFetch(
      target,
      new Request("http://container/ready"),
      async (response) => ({ status: response.status }),
      200,
    );
    expect(result.status).toBe(503);
    expect(cancelled).toBe(true);
    expect(Date.now() - started).toBeLessThan(1_000);
  });
});
