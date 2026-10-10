import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RouteCheckForm } from "@/components/RouteCheckForm";
import { apiError, mockApi, mockApiDown, stubNavigation } from "./helpers";

const ENVELOPE = {
  analysis_id: "ana_rc_1",
  trip_id: null,
  trip_token: null,
  kind: "route_check",
  status: "complete",
  demo_mode: true,
  demo_providers: {},
  latency_ms: 20,
  trace: {},
  result: {},
};

describe("RouteCheckForm", () => {
  let assign: ReturnType<typeof stubNavigation>;

  beforeEach(() => {
    assign = stubNavigation();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("cannot be submitted until there is an itinerary", () => {
    mockApi({});
    render(<RouteCheckForm />);
    expect(screen.getByRole("button", { name: "Check this route" })).toBeDisabled();
    expect(screen.getByText("Paste an itinerary to continue.")).toBeInTheDocument();
  });

  it("sends the example itinerary with the trip context and opens the result", async () => {
    const server = mockApi({ "POST /api/v1/route-check": { body: ENVELOPE } });
    render(<RouteCheckForm />);

    fireEvent.click(screen.getByRole("button", { name: "Use the example" }));
    expect(screen.getByLabelText("Your itinerary")).toHaveValue(
      "Tokyo 3 nights\nSendai 1 night\nGinzan Onsen 1 night\nAomori 1 night\nHakodate 1 night\nTokyo",
    );
    fireEvent.change(screen.getByLabelText("Flying out of"), { target: { value: "Sapporo" } });
    fireEvent.click(screen.getByLabelText("Large suitcases"));
    fireEvent.click(screen.getByRole("button", { name: "Check this route" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/route-check/result/ana_rc_1"));

    expect(server.calls).toHaveLength(1);
    expect(server.calls[0]!.body).toEqual({
      itinerary_text: "Tokyo 3 nights\nSendai 1 night\nGinzan Onsen 1 night\nAomori 1 night\nHakodate 1 night\nTokyo",
      stops: [],
      trip: {
        arrival_city: "Tokyo",
        departure_city: "Sapporo",
        driving: "no_car",
        pace: null,
        large_luggage: true,
        start_date: null,
      },
    });
  });

  it("sends named stops, and drops blank rows, when entered one by one", async () => {
    const server = mockApi({ "POST /api/v1/route-check": { body: ENVELOPE } });
    render(<RouteCheckForm />);

    fireEvent.click(screen.getByRole("tab", { name: "Enter stops one by one" }));
    expect(screen.getByText("Add at least two named stops.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Stop 1 name"), { target: { value: "Tokyo" } });
    fireEvent.change(screen.getByLabelText("Nights at stop 1"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Stop 2 name"), { target: { value: " Sendai " } });
    fireEvent.click(screen.getByRole("button", { name: "Add a stop" }));
    fireEvent.click(screen.getByRole("button", { name: "Check this route" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/route-check/result/ana_rc_1"));
    expect(server.calls[0]!.body).toMatchObject({
      itinerary_text: null,
      stops: [
        { name: "Tokyo", nights: 3 },
        { name: "Sendai", nights: 2 },
      ],
    });
  });

  it("surfaces an API failure and does not navigate", async () => {
    mockApi({ "POST /api/v1/route-check": apiError(503, "The transport provider is unavailable.", "provider_error") });
    render(<RouteCheckForm />);

    fireEvent.click(screen.getByRole("button", { name: "Use the example" }));
    fireEvent.click(screen.getByRole("button", { name: "Check this route" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The transport provider is unavailable.");
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Check this route" })).toBeEnabled();
    // What was typed survives the failure.
    expect((screen.getByLabelText("Your itinerary") as HTMLTextAreaElement).value).toContain("Ginzan Onsen 1 night");
  });

  it("explains when the analysis service cannot be reached at all", async () => {
    mockApiDown();
    render(<RouteCheckForm />);
    fireEvent.click(screen.getByRole("button", { name: "Use the example" }));
    fireEvent.click(screen.getByRole("button", { name: "Check this route" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not reach the analysis service/);
    expect(assign).not.toHaveBeenCalled();
  });
});
