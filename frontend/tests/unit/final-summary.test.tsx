import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FinalSummary } from "@/components/FinalSummary";

describe("FinalSummary", () => {
  it("shows the verdict, the next steps in order and the caveats", () => {
    render(
      <FinalSummary
        summary={{
          verdict: "Route health is needs improvement: 1 critical problem and 2 warnings.",
          next_steps: ["Switch to the revised route.", "Book the ryokan early."],
          caveats: ["Sources disagree on the last bus; that detail is unconfirmed."],
          source: "model",
        }}
      />,
    );
    expect(screen.getByText(/Route health is needs improvement/)).toBeInTheDocument();
    const steps = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(steps[0]).toContain("Switch to the revised route.");
    expect(steps[1]).toContain("Book the ryokan early.");
    expect(screen.getByText("Hold loosely")).toBeInTheDocument();
    expect(screen.getByText(/Sources disagree on the last bus/)).toBeInTheDocument();
  });

  it("leaves out the headings for lists that are empty", () => {
    render(<FinalSummary summary={{ verdict: "This itinerary holds up.", next_steps: [], caveats: [], source: "deterministic" }} />);
    expect(screen.getByText("This itinerary holds up.")).toBeInTheDocument();
    expect(screen.queryByText("What to do next")).not.toBeInTheDocument();
    expect(screen.queryByText("Hold loosely")).not.toBeInTheDocument();
  });

  it("renders nothing for an analysis stored before summaries existed", () => {
    const { container } = render(<FinalSummary summary={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
