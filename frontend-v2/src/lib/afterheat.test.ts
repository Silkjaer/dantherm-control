import { describe, expect, it } from "vitest";
import { hasAfterheat } from "./afterheat";
import { visibleSections } from "../pages/SettingsPage";

const admin = () => true;
const ids = (unit: Record<string, unknown>) => visibleSections(admin, unit).map(section => section.id);

describe("afterheat visibility", () => {
  it("shows afterheat on an MK1 with HAC1 or while HAC1 is still unknown", () => {
    expect(hasAfterheat({})).toBe(true);
    expect(hasAfterheat({ hac1_presence: "unknown" })).toBe(true);
    expect(hasAfterheat({ hac1_presence: "present" })).toBe(true);
  });

  it("hides afterheat on an MK1 without HAC1 and on an MKII", () => {
    expect(hasAfterheat({ hac1_presence: "absent" })).toBe(false);
    expect(hasAfterheat({ unit_generation: "mk2" })).toBe(false);
  });

  it("drops the afterheat settings section only when there is no afterheat", () => {
    expect(ids({ hac1_presence: "present" })).toContain("afterheat");
    expect(ids({ hac1_presence: "absent" })).not.toContain("afterheat");
    expect(ids({ hac1_presence: "absent" })).toContain("cooling");
  });
});
