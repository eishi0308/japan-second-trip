import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RouteTimeline } from "@/components/RouteTimeline";

const route = {
  arrival_city: "Tokyo",
  departure_city: "Tokyo",
  stops: [
    { order: 0, raw_name: "Tokyo", place_slug: "tokyo", display_name: "Tokyo", nights: 3, region_code: null, lat: 35.7, lon: 139.8, resolved: true, resolution_note: null },
    { order: 1, raw_name: "Ginzan", place_slug: "ginzan-onsen", display_name: "Ginzan Onsen", nights: 1, region_code: "tohoku", lat: 38.6, lon: 140.5, resolved: true, resolution_note: "Matched 'Ginzan' to Ginzan Onsen." },
    { order: 2, raw_name: "Nowhere", place_slug: null, display_name: null, nights: 1, region_code: null, lat: null, lon: null, resolved: false, resolution_note: "Not in the place catalogue." },
  ],
  segments: [
    { from_order: 0, to_order: 1, from_name: "Tokyo", to_name: "Ginzan Onsen", mode: "local_train", duration_minutes: 195, transfers: 2, distance_km: 105, requires_car: false, last_departure_local: "18:10", final_leg_minutes: 40, provider: "demo", is_estimate: false, evidence_ids: [], notes: null },
    { from_order: 1, to_order: 2, from_name: "Ginzan Onsen", to_name: "Nowhere", mode: "car", duration_minutes: 90, transfers: 0, distance_km: 50, requires_car: true, last_departure_local: null, final_leg_minutes: null, provider: "demo", is_estimate: true, evidence_ids: [], notes: null },
  ],
};

describe("RouteTimeline", () => {
  it("shows nights and real durations", () => {
    render(<RouteTimeline route={route} />);
    expect(screen.getByText("Tokyo")).toBeInTheDocument();
    expect(screen.getByText("3 nights")).toBeInTheDocument();
    expect(screen.getByText("3.3h")).toBeInTheDocument();
    expect(screen.getByText("2 transfers")).toBeInTheDocument();
  });

  it("marks an unidentified stop instead of quietly dropping it", () => {
    render(<RouteTimeline route={route} />);
    expect(screen.getByText("not identified")).toBeInTheDocument();
  });

  it("distinguishes an estimate from a verified duration", () => {
    render(<RouteTimeline route={route} />);
    expect(screen.getByText("estimated")).toBeInTheDocument();
    expect(screen.getByText("car required")).toBeInTheDocument();
  });

  it("surfaces the last connection of the day", () => {
    render(<RouteTimeline route={route} />);
    expect(screen.getByText(/last connection 18:10/)).toBeInTheDocument();
  });
});
