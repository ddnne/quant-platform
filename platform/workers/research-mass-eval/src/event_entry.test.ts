import { describe, expect, it } from "vitest";
import { afterClose, discTimeKnown, pitEventEntryShift } from "./event_entry";

describe("PIT event entry", () => {
  it("does not treat missing DiscTime as same-day", () => {
    expect(discTimeKnown(null)).toBe(false);
    expect(discTimeKnown("")).toBe(false);
    expect(afterClose(null)).toBe(false);
    expect(pitEventEntryShift(null)).toBe(1);
    expect(pitEventEntryShift("")).toBe(1);
  });

  it("pre-close stays same day; after close next session", () => {
    expect(pitEventEntryShift("12:00:00")).toBe(0);
    expect(pitEventEntryShift("15:00:00")).toBe(1);
    expect(afterClose("15:00:00")).toBe(true);
  });

  it("invented midnight clock is not same-day", () => {
    // Sibling: tests/test_class_signals.py::test_python_worker_disctime_midnight_invent_is_next_session
    expect(discTimeKnown("00:00:00")).toBe(false);
    expect(discTimeKnown("00:00")).toBe(false);
    expect(pitEventEntryShift("00:00:00")).toBe(1);
    expect(afterClose("00:00:00")).toBe(false);
  });
});
