import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  ConfidenceBadge,
  FitBadge,
  FreshnessBadge,
  HealthBadge,
  SeverityBadge,
} from "@/components/primitives";

describe("status badges", () => {
  it("names a rejected region plainly rather than euphemistically", () => {
    render(<FitBadge label="not_recommended" />);
    expect(screen.getByText("Not recommended for this trip")).toBeInTheDocument();
  });

  it.each([
    ["healthy", "Healthy"],
    ["needs_improvement", "Needs improvement"],
    ["high_risk", "High risk"],
  ] as const)("renders %s health as %s", (health, label) => {
    render(<HealthBadge health={health} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("does not soften a critical issue", () => {
    render(<SeverityBadge severity="critical" />);
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });

  it("surfaces insufficient evidence as its own state", () => {
    render(<ConfidenceBadge confidence="insufficient_evidence" />);
    expect(screen.getByText("Insufficient evidence")).toBeInTheDocument();
  });
});

describe("freshness", () => {
  it("always shows the verification date, never a bare 'verified'", () => {
    render(<FreshnessBadge freshness="fresh" verifiedAt="2026-07-01T00:00:00Z" />);
    expect(screen.getByText(/Verified · 2026-07-01/)).toBeInTheDocument();
  });

  it("says out of date rather than hiding staleness", () => {
    render(<FreshnessBadge freshness="stale" verifiedAt="2024-01-01T00:00:00Z" />);
    expect(screen.getByText(/Out of date/)).toBeInTheDocument();
  });

  it("distinguishes never-verified from verified-long-ago", () => {
    render(<FreshnessBadge freshness="unverified" verifiedAt={null} />);
    expect(screen.getByText("Not verified")).toBeInTheDocument();
  });
});
