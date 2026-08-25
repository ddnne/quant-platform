import { afterEach, describe, expect, it, vi } from "vitest";
import { newRunId } from "./identity";

const UUID = "11111111-1111-4111-8111-111111111111";

describe("newRunId", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses crypto.randomUUID and does not call Math.random", () => {
    const randomSpy = vi.spyOn(Math, "random");
    const uuidSpy = vi.spyOn(crypto, "randomUUID").mockReturnValue(UUID);

    expect(newRunId("scd2")).toBe(`scd2-${UUID}`);
    expect(newRunId("r2-equities_master")).toBe(`r2-equities_master-${UUID}`);

    expect(uuidSpy).toHaveBeenCalledTimes(2);
    expect(randomSpy).not.toHaveBeenCalled();
  });
});
