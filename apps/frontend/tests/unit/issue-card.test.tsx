import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { IssueCard } from "@/components/IssueCard";
import type { RouteIssue } from "@/lib/types";

const issue: RouteIssue = {
  issue_type: "travel_burden",
  severity: "critical",
  segment: "Ginzan Onsen → Aomori",
  title: "Ginzan Onsen → Aomori costs more time than it buys",
  explanation: "The hop takes about 5.5h. With 1 night at Aomori that leaves roughly 3.5h there.",
  deterministic_signal: { segment_hours: 5.5, nights_at_destination: 1, usable_hours: 3.5 },
  rule_id: "R01_travel_burden",
  evidence_ids: ["ev_1"],
  proposed_fix: "Give Aomori a second night, or drop it.",
};

describe("IssueCard", () => {
  it("shows the segment, the verdict and the fix", () => {
    render(<IssueCard issue={issue} />);
    expect(screen.getByText(issue.title)).toBeInTheDocument();
    expect(screen.getByText("Ginzan Onsen → Aomori")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText(/Give Aomori a second night/)).toBeInTheDocument();
  });

  it("exposes the measurements behind the verdict", () => {
    render(<IssueCard issue={issue} />);
    expect(screen.getByText("The measurements behind this")).toBeInTheDocument();
    expect(screen.getByText("segment hours")).toBeInTheDocument();
    expect(screen.getByText("5.5")).toBeInTheDocument();
    expect(screen.getByText(/R01_travel_burden/)).toBeInTheDocument();
  });

  it("renders a positive finding as a strength, not a problem", () => {
    render(
      <IssueCard
        issue={{ ...issue, severity: "good", title: "Tokyo → Sendai is efficient", proposed_fix: null }}
      />,
    );
    expect(screen.getByText("Working well")).toBeInTheDocument();
  });
});
