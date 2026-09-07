import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfidenceNotice } from "@/components/ConfidenceNotice";

describe("ConfidenceNotice", () => {
  it("tells the traveller when a person has been asked to check something", () => {
    render(
      <ConfidenceNotice
        confidence="medium"
        humanReviewRequired
        humanReviewTaskId="hr_123"
        conflicts={[
          {
            field_name: "last_shuttle_departure",
            subject: "ginzan-onsen:oishida_last_bus",
            values: ["17:00", "16:30"],
            evidence_ids: ["ev_1", "ev_2"],
          },
        ]}
      />,
    );
    expect(screen.getByText("Sent for human verification")).toBeInTheDocument();
    expect(screen.getByText(/hr_123/)).toBeInTheDocument();
  });

  it("shows both disputed values rather than picking one", () => {
    render(
      <ConfidenceNotice
        confidence="medium"
        humanReviewRequired
        humanReviewTaskId={null}
        conflicts={[
          { field_name: "last_bus", subject: "ginzan", values: ["17:00", "16:30"], evidence_ids: [] },
        ]}
      />,
    );
    const text = screen.getByText(/17:00/);
    expect(text.textContent).toContain("16:30");
  });

  it("states assumptions instead of burying them", () => {
    render(
      <ConfidenceNotice
        confidence="high"
        humanReviewRequired={false}
        humanReviewTaskId={null}
        assumptions={["No regional-nights figure given; assumed 3 nights."]}
      />,
    );
    expect(screen.getByText("Assumptions made")).toBeInTheDocument();
    expect(screen.getByText(/assumed 3 nights/)).toBeInTheDocument();
  });

  it("credits the reviewer when a fact was confirmed by a human", () => {
    render(
      <ConfidenceNotice
        confidence="high"
        humanReviewRequired={false}
        humanReviewTaskId={null}
        resolvedFacts={[
          {
            subject: "ginzan-onsen:oishida_last_bus",
            field: "last_shuttle_departure",
            value: "17:00",
            verified_by: "eishi",
            verified_at: "2026-09-06T13:00:00Z",
          },
        ]}
      />,
    );
    expect(screen.getByText("Confirmed by a reviewer")).toBeInTheDocument();
    expect(screen.getByText(/verified by eishi on 2026-09-06/)).toBeInTheDocument();
  });

  it("says so plainly when nothing needed caveating", () => {
    render(<ConfidenceNotice confidence="high" humanReviewRequired={false} humanReviewTaskId={null} />);
    expect(screen.getByText(/No assumptions, unknowns or source conflicts/)).toBeInTheDocument();
  });
});
