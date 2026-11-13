import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { IssueList } from "@/components/v2/CheckViews";
import { NotForThisTrip, OptionCard } from "@/components/v2/OptionCard";
import { FactMark, FitLevel, VerdictMark } from "@/components/v2/ui";
import { applySuggestion } from "@/lib/v2";
import { issue, option } from "../fixtures/v2";

describe("status marks", () => {
  it("never says Checked without a date", () => {
    render(<FactMark state="verified" date="2026-10-14T00:00:00Z" />);
    expect(screen.getByText(/Checked 14 Oct 2026/)).toBeInTheDocument();
  });

  it("says Being checked for a disputed fact", () => {
    render(<FactMark state="being_checked" date="2026-10-14T00:00:00Z" />);
    expect(screen.getByText("Being checked")).toBeInTheDocument();
  });

  it("pairs every verdict with words, not colour alone", () => {
    render(<VerdictMark verdict="will_not_work" label="Will not work" />);
    const mark = screen.getByText("Will not work");
    expect(mark.querySelector("svg")).not.toBeNull();
  });

  it("shows fit as one of five levels", () => {
    render(<FitLevel level={4} label="Strong fit" />);
    expect(screen.getByLabelText("Strong fit, 4 of 5")).toBeInTheDocument();
  });
});

describe("option card", () => {
  it("follows the spec order and shows no percentages", () => {
    const { container } = render(<OptionCard option={option} />);
    const text = container.textContent ?? "";
    const order = ["Unexpected", "Morioka + Nyuto Onsen", "Noodles", "Strong fit", "8h20 moving", "No car needed", "January: a good time", "What's hard", "Checked 14 Oct 2026"];
    const positions = order.map((s) => text.indexOf(s));
    expect(positions.every((p) => p >= 0)).toBe(true);
    expect([...positions].sort((a, b) => a - b)).toEqual(positions);
    expect(text).not.toContain("%");
  });

  it("lists What's hard items", () => {
    render(<OptionCard option={option} />);
    expect(screen.getByText("Nyuto Onsen: Last bus from Tazawako Station")).toBeInTheDocument();
  });
});

describe("not for this trip", () => {
  it("states the reason and what would change it", () => {
    render(
      <NotForThisTrip
        rejections={[
          { area: "kyushu", area_label: "Kyushu", example: "Beppu", reason: "Heavy travel from Tokyo.", if_you_change: "If you can fly out of Fukuoka, Kyushu becomes a possible option." },
        ]}
      />,
    );
    expect(screen.getByText(/If you can fly out of Fukuoka/)).toBeInTheDocument();
  });
});

describe("issues and fixes", () => {
  it("shows the problem, why, review note, evidence and a gain/lose diff", () => {
    const onApply = vi.fn();
    render(<IssueList issues={[issue]} onApply={onApply} />);
    expect(screen.getByText(issue.title)).toBeInTheDocument();
    expect(screen.getByText(/A reviewer has been asked/)).toBeInTheDocument();
    expect(screen.getByText(/DEMO record, sources disagree/)).toBeInTheDocument();
    const fix = screen.getByText("Leave Sendai at 07:30 instead of 09:30").closest("div") as HTMLElement;
    expect(within(fix).getByText(/Earlier start/)).toBeInTheDocument();
    fireEvent.click(within(fix).getByRole("button", { name: "Apply this fix" }));
    expect(onApply).toHaveBeenCalledWith(issue.fixes[0]);
  });
});

describe("zero-results suggestions", () => {
  const set = { month: 1, nights: 4, options: [], not_for_this_trip: [], funnel: [], zero_results_suggestions: [] };
  it.each([
    ["can_drive", { transport: "either" }],
    ["nights_plus_2", { regional_nights: 6 }],
    ["month_2", { month: 2 }],
  ])("%s changes the request", (change, expected) => {
    expect(applySuggestion({ month: 1, regional_nights: 4 }, change, set)).toMatchObject(expected);
  });

  it("un-pins only the named stop", () => {
    const req = { must_include: ["Shirakawa-go", "Takayama"] };
    expect(applySuggestion(req, "unpin_shirakawa-go", set).must_include).toEqual(["Takayama"]);
  });
});
