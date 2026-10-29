import type { Lang } from "./i18n";

/** Where the room temperature that free cooling and the afterheat steer by
 *  comes from, as the controller reports it in afterheat_room_source_used:
 *  "ha_average", "t3", "t5" or "room:<name>". Short fits a narrow tile. */
export function roomSourceLabel(used: unknown, lang: Lang = "da", short = false): string {
  const value = used === null || used === undefined ? "" : String(used);
  if (!value) return "—";
  if (value === "ha_average") {
    if (short) return lang === "da" ? "HA-rum" : "HA rooms";
    return lang === "da" ? "Gennemsnit af HA-rum" : "Average of HA rooms";
  }
  if (value.startsWith("room:")) return value.slice(5);
  return value.toUpperCase();
}
