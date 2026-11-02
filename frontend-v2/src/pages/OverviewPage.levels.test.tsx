// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { OverviewPage } from "./OverviewPage";

const api = vi.hoisted(() => ({ requestJson: vi.fn(), postJson: vi.fn() }));
vi.mock("../lib/api", () => ({ requestJson: api.requestJson, postJson: api.postJson }));

class ResizeObserverStub { observe() {} disconnect() {} }
vi.stubGlobal("ResizeObserver", ResizeObserverStub);

afterEach(() => { cleanup(); api.requestJson.mockReset(); api.postJson.mockReset(); });

function serve(controller: Record<string, unknown>) {
  api.requestJson.mockImplementation(async (endpoint: string) => {
    if (endpoint === "/state.json") return {};
    if (endpoint === "/api/controller/state?compact=1") return controller;
    if (endpoint === "/api/auth/status") return { csrf: "test" };
    throw new Error(endpoint);
  });
  api.postJson.mockImplementation(async (_endpoint: string, patch: Record<string, unknown>) => ({ ...controller, ...patch }));
}

describe("level buttons", () => {
  it("run the level by hand in Auto instead of changing Auto's normal level", async () => {
    serve({ mode: "smart_auto", fan_step_count: 6, max_level: 6, effective_level: 2, local_normal_level: 2 });
    render(<OverviewPage/>);
    fireEvent.click(await screen.findByRole("button", { name: "6" }));
    await waitFor(() => expect(api.postJson).toHaveBeenCalledWith("/api/controller/config", { mode: "manual", manual_level: 6 }, "test"));
  });

  it("switch the unit on at the chosen level from standby", async () => {
    serve({ mode: "local_auto", fan_step_count: 4, max_level: 4, effective_level: 3, standby: true, standby_active: true });
    render(<OverviewPage/>);
    fireEvent.click(await screen.findByRole("button", { name: "2" }));
    await waitFor(() => expect(api.postJson).toHaveBeenCalledWith("/api/controller/config", { standby_minutes: 0, mode: "manual", manual_level: 2 }, "test"));
  });
});
