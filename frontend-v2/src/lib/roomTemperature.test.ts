import { describe, expect, it } from "vitest";
import { roomSourceLabel } from "./roomTemperature";

describe("room temperature source", () => {
  it("names the source the controller reports", () => {
    expect(roomSourceLabel("ha_average")).toBe("Gennemsnit af HA-rum");
    expect(roomSourceLabel("ha_average", "en")).toBe("Average of HA rooms");
    expect(roomSourceLabel("room:Stue")).toBe("Stue");
    expect(roomSourceLabel("t3")).toBe("T3");
    expect(roomSourceLabel(null)).toBe("—");
  });
});
