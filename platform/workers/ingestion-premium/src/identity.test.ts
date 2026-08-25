import { afterEach, describe, expect, it, vi } from "vitest";
import { newRunId, sessionCloseJst } from "./identity";

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

describe("sessionCloseJst", () => {
  it("uses 15:00 before 2024-11-05, 15:30 from that date, and 11:30 for morning", () => {
    expect(sessionCloseJst("2024-11-04")).toBe("2024-11-04T15:00:00+09:00");
    expect(sessionCloseJst("2024-11-05")).toBe("2024-11-05T15:30:00+09:00");
    expect(sessionCloseJst("2025-04-01")).toBe("2025-04-01T15:30:00+09:00");
    expect(sessionCloseJst("2025-04-01", "morning")).toBe(
      "2025-04-01T11:30:00+09:00",
    );
  });
});
