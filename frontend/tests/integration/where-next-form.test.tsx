import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { WhereNextForm } from "@/components/WhereNextForm";
import { apiError, mockApi, mockApiDown, stubNavigation } from "./helpers";

const ENVELOPE = {
  analysis_id: "ana_123",
  trip_id: "trp_9",
  trip_token: "secret-token",
  kind: "where_next",
  status: "complete",
  demo_mode: true,
  demo_providers: {},
  latency_ms: 12,
  trace: {},
  result: {},
};

function fillAllSteps() {
  fireEvent.change(screen.getByLabelText("Total nights in Japan"), { target: { value: "12" } });
  fireEvent.change(screen.getByLabelText(/Nights in the region/), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText(/Flying out of/), { target: { value: "Osaka" } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));

  // Step 2: Tokyo, Kyoto and Osaka start selected. Add one, remove one.
  fireEvent.click(screen.getByRole("button", { name: "Kanazawa" }));
  fireEvent.click(screen.getByRole("button", { name: "Osaka" }));
  fireEvent.change(screen.getByLabelText(/Anything else about this trip/), {
    target: { value: "Third trip, want quiet." },
  });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));

  fireEvent.click(screen.getByRole("button", { name: "food" }));
  fireEvent.click(screen.getByRole("button", { name: "onsen" }));
  fireEvent.change(screen.getByLabelText(/Will you drive\?/), { target: { value: "no_car" } });
  fireEvent.change(screen.getByLabelText(/^Pace/), { target: { value: "relaxed" } });
  fireEvent.click(screen.getByLabelText("Step-free access is required"));
}

describe("WhereNextForm", () => {
  let assign: ReturnType<typeof stubNavigation>;

  beforeEach(() => {
    assign = stubNavigation();
    window.localStorage.clear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("submits what was entered across the three steps and opens the result", async () => {
    const server = mockApi({ "POST /api/v1/where-next": { body: ENVELOPE } });
    render(<WhereNextForm />);

    expect(screen.getByRole("heading", { name: "The trip" })).toBeInTheDocument();
    fillAllSteps();
    expect(screen.getByRole("heading", { name: "How you travel" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Compare regions" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/where-next/result/ana_123"));

    expect(server.calls).toHaveLength(1);
    expect(server.calls[0]!.body).toEqual({
      trip: {
        start_date: null,
        total_nights: 12,
        regional_nights: 3,
        arrival_city: "Tokyo",
        departure_city: "Osaka",
        visited_places: ["Tokyo", "Kyoto", "Kanazawa"],
        traveller_type: null,
        interests: ["food", "onsen"],
        driving: "no_car",
        budget: null,
        pace: "relaxed",
        large_luggage: false,
        mobility: { step_free_required: true, limited_walking: false, notes: null },
        free_text: "Third trip, want quiet.",
      },
    });
    // The trip token is kept so the workspace can be reopened from this browser.
    expect(window.localStorage.getItem("jst.trip.trp_9")).toBe("secret-token");
  });

  it("can be submitted from the first step with nothing filled in", async () => {
    const server = mockApi({ "POST /api/v1/where-next": { body: ENVELOPE } });
    render(<WhereNextForm />);

    fireEvent.click(screen.getByRole("button", { name: "Skip the rest" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/where-next/result/ana_123"));
    expect(server.calls[0]!.body).toMatchObject({
      trip: { total_nights: null, regional_nights: null, interests: [], driving: null, mobility: null },
    });
  });

  it("announces that it is working while the analysis runs", async () => {
    mockApi({ "POST /api/v1/where-next": { body: ENVELOPE } });
    render(<WhereNextForm />);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    fireEvent.click(screen.getByRole("button", { name: "Compare regions" }));

    expect(screen.getByRole("button", { name: "Analysing…" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/Scoring every region/);
    await waitFor(() => expect(assign).toHaveBeenCalled());
  });

  it("shows the API's own message when the request is rejected, and stays on the form", async () => {
    mockApi({
      "POST /api/v1/where-next": apiError(422, "regional_nights cannot exceed total_nights", "validation_failed"),
    });
    render(<WhereNextForm />);
    fireEvent.click(screen.getByRole("button", { name: "Skip the rest" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("regional_nights cannot exceed total_nights");
    expect(assign).not.toHaveBeenCalled();
    // The form is usable again, so the traveller can correct it and resubmit.
    expect(screen.getByRole("button", { name: "Skip the rest" })).toBeEnabled();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("explains when the analysis service cannot be reached at all", async () => {
    mockApiDown();
    render(<WhereNextForm />);
    fireEvent.click(screen.getByRole("button", { name: "Skip the rest" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not reach the analysis service/);
    expect(assign).not.toHaveBeenCalled();
  });
});
