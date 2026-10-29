// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { SettingsPage } from "./SettingsPage";

const api = vi.hoisted(() => ({ requestJson: vi.fn(), postJson: vi.fn() }));
vi.mock("../lib/api", () => ({ requestJson: api.requestJson, postJson: api.postJson }));
afterEach(() => { cleanup(); api.requestJson.mockReset(); window.location.hash = ""; });

function serve(unit: Record<string, unknown>) {
  api.requestJson.mockImplementation(async (endpoint: string) => {
    if (endpoint === "/state.json") return unit;
    if (endpoint.startsWith("/api/controller/state")) {
      return { afterheat_room_source: "auto", afterheat_room_source_used: "ha_average", afterheat_room_temperature: 22.88, measurement_rooms: ["Stue"] };
    }
    if (endpoint === "/api/auth/status") return { csrf: "csrf-test" };
    throw new Error(endpoint);
  });
}

describe("Free cooling settings", () => {
  it("shows the room temperature it steers by and where it comes from", async () => {
    serve({ hac1_presence: "present" });
    window.location.hash = "#/settings?section=cooling";
    render(<SettingsPage/>);
    expect(await screen.findByText("Gennemsnit af HA-rum")).toBeTruthy();
    expect(screen.getByText("22,9 °C")).toBeTruthy();
    // With afterheat the shared source stays in the afterheat section.
    expect(screen.queryByLabelText(/Rumtemperatur fra/)).toBeNull();
  });

  it("offers the room temperature source when there is no afterheat section", async () => {
    serve({ hac1_presence: "absent" });
    window.location.hash = "#/settings?section=cooling";
    render(<SettingsPage/>);
    await waitFor(() => expect(screen.queryByLabelText(/Rumtemperatur fra/)).not.toBeNull());
    const select = screen.getByLabelText(/Rumtemperatur fra/) as HTMLSelectElement;
    expect(select.value).toBe("auto");
    expect([...select.options].map(option => option.value)).toContain("room:Stue");
    expect(screen.getByText(/Frikøling og eftervarme styrer efter den samme rumtemperatur/)).toBeTruthy();
  });
});
