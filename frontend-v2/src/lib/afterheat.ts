/** Whether the unit has an afterheat module whose controls and readings are
 *  worth showing. An MKII has none over Modbus, and on an MK1 without HAC1 the
 *  gateway reports hac1_presence "absent". Unknown counts as present, so
 *  nothing disappears while the gateway is still finding out. */
export function hasAfterheat(unit: Record<string, unknown>): boolean {
  return unit.unit_generation !== "mk2" && unit.hac1_presence !== "absent";
}
