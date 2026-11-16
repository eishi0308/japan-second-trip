import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TripNotices } from "@/components/v2/TripNotices";
import { VerificationQueue } from "@/components/v2/VerificationQueue";

const item = {
  fact_id: "frg_1",
  destination: "Ginzan Onsen",
  destination_slug: "ginzan-onsen",
  kind: "last_connection",
  title: "Last bus from Oishida Station",
  detail: "Sources disagree on the winter last departure.",
  state: "being_checked",
  severity: "critical",
  current_value: null,
  candidate_values: ["17:00", "16:30", "18:10"],
  verified_at: "2026-09-20T00:00:00Z",
  task_id: "hr_1",
  trips_affected: 2,
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

describe("verification queue", () => {
  it("asks for a token, lists facts, and resolves one with a time", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(json({ items: [item], count: 1 }))
      .mockResolvedValueOnce(json({ fact_id: "frg_1", value: "17:00", verification_id: "ver_1", tasks_closed: 1, trips_updated: [{ trip_id: "t1", verdict_before: "needs_attention", verdict_after: "works" }, { trip_id: "t2", verdict_before: "works", verdict_after: "works" }] }))
      .mockResolvedValueOnce(json({ items: [], count: 0 }));
    render(<VerificationQueue />);
    fireEvent.change(screen.getByLabelText("Admin token"), { target: { value: "secret" } });
    fireEvent.click(screen.getByRole("button", { name: "Open the queue" }));

    expect(await screen.findByText(/Ginzan Onsen: Last bus from Oishida Station/)).toBeInTheDocument();
    expect(screen.getByText("Being checked")).toBeInTheDocument();
    expect(screen.getByText(/Reported values: 17:00, 16:30, 18:10/)).toBeInTheDocument();
    expect(screen.getByText(/2 saved trips depend on this/)).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Confirmed time"), { target: { value: "17:00" } });
    fireEvent.click(screen.getByRole("button", { name: "Confirm this time" }));

    expect(await screen.findByText(/Resolved as 17:00\. 1 task closed, 2 saved trips re-checked and notified/)).toBeInTheDocument();
    const body = JSON.parse((fetchSpy.mock.calls[1]![1] as RequestInit).body as string);
    expect(body).toMatchObject({ value: "17:00", reviewer: "admin" });
    expect((fetchSpy.mock.calls[1]![1] as RequestInit).headers).toMatchObject({ Authorization: "Bearer secret" });
    await waitFor(() => expect(screen.getByText(/Nothing to check/)).toBeInTheDocument());
  });

  it("says when the token is rejected", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ error: { message: "no", code: "unauthorized" } }, 401));
    render(<VerificationQueue />);
    fireEvent.change(screen.getByLabelText("Admin token"), { target: { value: "wrong" } });
    fireEvent.click(screen.getByRole("button", { name: "Open the queue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That token was rejected.");
  });
});

describe("trip notices", () => {
  const notice = {
    at: "2026-11-17T01:00:00Z",
    fact_id: "frg_1",
    text: "Ginzan Onsen: last bus from oishida station confirmed as 17:00 on 17 Nov 2026. We re-checked your trip: Needs attention → Works.",
    verdict_before: "needs_attention" as const,
    verdict_after: "works" as const,
    seen: false,
  };

  it("shows what changed and lets the owner mark it read", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(json({ notices: [{ ...notice, seen: true }] }));
    render(<TripNotices notices={[notice]} trip={{ id: "t1", token: "tok" }} />);
    expect(screen.getByText(/Updates to your trip \(1 new\)/)).toBeInTheDocument();
    expect(screen.getByText(/Needs attention → Works/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Mark as read" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Mark as read" })).toBeNull());
  });

  it("shows nothing when there are no updates", () => {
    const { container } = render(<TripNotices notices={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});
