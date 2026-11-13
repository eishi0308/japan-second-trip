import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PlanForm } from "@/components/v2/PlanForm";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const cities = [{ slug: "tokyo", name: "Tokyo", area: "kanto", is_international_gateway: true }];
const cards = [
  { slug: "snowy-onsen-town", title: "Snowy onsen town", themes: ["onsen", "snow"] },
  { slug: "fishing-village", title: "Fishing village by the sea", themes: ["coast", "food"] },
];

function respond(body: unknown) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(body), { status: 200 }));
}

describe("plan form", () => {
  beforeEach(() => push.mockReset());

  it("starts with every required field Not decided yet and Tokyo/Kyoto/Osaka visited", () => {
    render(<PlanForm cities={cities} sceneCards={cards} />);
    expect(screen.getByLabelText("Travel month")).toHaveValue("");
    expect(screen.getByLabelText("Regional nights")).toHaveValue("");
    expect(screen.getByLabelText("Arrival city")).toHaveValue("");
    for (const city of ["Tokyo", "Kyoto", "Osaka"]) expect(screen.getByRole("button", { name: new RegExp(`^${city}`) })).toBeInTheDocument();
  });

  it("allows at most three interests", () => {
    render(<PlanForm cities={cities} sceneCards={cards} />);
    for (const i of ["food", "onsen", "snow"]) fireEvent.click(screen.getByRole("button", { name: i }));
    expect(screen.getByRole("button", { name: "art" })).toBeDisabled();
  });

  it("hides the helpers once interests are picked", () => {
    render(<PlanForm cities={cities} sceneCards={cards} />);
    expect(screen.getByLabelText("Best moment on your last Japan trip")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "food" }));
    expect(screen.queryByLabelText("Best moment on your last Japan trip")).toBeNull();
  });

  it("sends undecided fields as null with scene cards and past-trip answers, then shows real counts", async () => {
    const fetchSpy = respond({
      plan_id: "plan_1",
      request: {},
      plan: {
        kind: "season_choice",
        assumptions: [],
        interests: [],
        notices: [],
        result: null,
        seasons: [{ season: "winter", label: "Winter", month: 1, result: { funnel: [{ label: "places in the database", count: 149 }] } }],
        nights_options: [],
        is_demo: true,
      },
      preferences: { interests: [], avoid: [], source: "deterministic" },
      demo_mode: true,
      latency_ms: 1,
    });
    render(<PlanForm cities={cities} sceneCards={cards} />);
    fireEvent.change(screen.getByLabelText("Best moment on your last Japan trip"), { target: { value: "Loved Nishiki Market food walks, tired of crowds" } });
    fireEvent.click(screen.getByRole("button", { name: "Snowy onsen town" }));
    fireEvent.click(screen.getByRole("button", { name: "Fishing village by the sea" }));
    fireEvent.click(screen.getByRole("button", { name: "Show me three trips" }));

    await waitFor(() => expect(fetchSpy).toHaveBeenCalled());
    const body = JSON.parse((fetchSpy.mock.calls[0]![1] as RequestInit).body as string);
    expect(body).toMatchObject({
      month: null,
      regional_nights: null,
      arrival_city: null,
      departure_city: null,
      scene_cards: ["snowy-onsen-town", "fishing-village"],
      past_trip_best: "Loved Nishiki Market food walks, tired of crowds",
      transport: "no_car",
    });
    expect(await screen.findByText("149")).toBeInTheDocument();
    await waitFor(() => expect(push).toHaveBeenCalledWith("/plan/plan_1"), { timeout: 3000 });
  });

  it("explains when the planner is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("offline"));
    render(<PlanForm cities={cities} sceneCards={cards} />);
    fireEvent.click(screen.getByRole("button", { name: "Show me three trips" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("could not reach the planner");
  });
});
