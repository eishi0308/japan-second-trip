import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import DemoCheckoutPage from "@/app/checkout/demo/page";
import CheckoutReturnPage from "@/app/checkout/return/page";
import { CheckoutButton } from "@/components/CheckoutButton";
import { PurchaseOfferView } from "@/components/PurchaseOffer";
import type { Purchase } from "@/lib/types";
import { apiError, mockApi, mockApiDown, stubNavigation } from "./helpers";

const purchase = (overrides: Partial<Purchase> = {}): Purchase => ({
  id: "pur_1",
  plan_id: "verified_route",
  plan_name: "Verified Regional Route",
  amount_aud: 29,
  status: "pending",
  provider: "demo",
  is_demo: true,
  analysis_id: "ana_123",
  trip_id: "trp_9",
  paid_at: null,
  ...overrides,
});

/** Pages are async server components that only read the query string; resolve them, then render. */
async function renderDemoPage(query: Record<string, string>) {
  render(await DemoCheckoutPage({ searchParams: Promise.resolve(query) }));
}
async function renderReturnPage(query: Record<string, string>) {
  render(await CheckoutReturnPage({ searchParams: Promise.resolve(query) }));
}

let assign: ReturnType<typeof stubNavigation>;
beforeEach(() => {
  assign = stubNavigation();
});
afterEach(() => vi.unstubAllGlobals());

describe("starting a checkout", () => {
  it("posts the plan and analysis, then sends the traveller to the checkout URL the API returns", async () => {
    const server = mockApi({
      "POST /api/v1/billing/checkout": {
        status: 201,
        body: {
          purchase: purchase(),
          checkout_url: "http://localhost:3000/checkout/demo?purchase=pur_1",
          mode: "demo",
        },
      },
    });
    render(
      <CheckoutButton planId="verified_route" analysisId="ana_123" tripId="trp_9">
        Buy Verified Regional Route
      </CheckoutButton>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Buy Verified Regional Route" }));
    expect(screen.getByRole("button", { name: "Starting checkout…" })).toBeDisabled();

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith("http://localhost:3000/checkout/demo?purchase=pur_1"),
    );
    expect(server.calls).toEqual([
      {
        method: "POST",
        path: "/api/v1/billing/checkout",
        body: { plan_id: "verified_route", analysis_id: "ana_123", trip_id: "trp_9" },
      },
    ]);
  });

  it("follows a Stripe URL on another origin unchanged", async () => {
    mockApi({
      "POST /api/v1/billing/checkout": {
        status: 201,
        body: {
          purchase: purchase({ provider: "stripe", is_demo: false, plan_id: "route_check" }),
          checkout_url: "https://checkout.stripe.com/c/pay/cs_test_abc",
          mode: "stripe_test",
        },
      },
    });
    render(
      <CheckoutButton planId="route_check" analysisId="ana_rc_1">
        Buy RouteCheck
      </CheckoutButton>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Buy RouteCheck" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://checkout.stripe.com/c/pay/cs_test_abc"));
  });

  it("shows why a checkout could not start, stays put, and can be tried again", async () => {
    mockApi({
      "POST /api/v1/billing/checkout": apiError(502, "Stripe could not start the checkout. Try again shortly."),
    });
    render(
      <CheckoutButton planId="route_check" analysisId="ana_rc_1">
        Buy RouteCheck
      </CheckoutButton>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Buy RouteCheck" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Stripe could not start the checkout.");
    expect(assign).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Buy RouteCheck" })).toBeEnabled();
  });

  it("says nothing was charged when the payment service is unreachable", async () => {
    mockApiDown();
    render(<CheckoutButton planId="route_check">Buy RouteCheck</CheckoutButton>);
    fireEvent.click(screen.getByRole("button", { name: "Buy RouteCheck" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(/Nothing was charged/);
    expect(assign).not.toHaveBeenCalled();
  });
});

describe("the purchase offer on a result page", () => {
  it("shows the price it was given and labels a demo checkout as one", () => {
    mockApi({});
    render(
      <PurchaseOfferView
        planId="route_check"
        analysisId="ana_rc_1"
        tripId={null}
        priceAud={19}
        mode="demo"
        paid={null}
      />,
    );
    const offer = screen.getByRole("region", { name: "RouteCheck" });
    expect(within(offer).getByText("A$19")).toBeInTheDocument();
    expect(within(offer).getByText("Demo checkout · no charge")).toBeInTheDocument();
    expect(within(offer).getByRole("button", { name: "Buy RouteCheck" })).toBeEnabled();
  });

  it("replaces the buy button with the purchase once it is paid", () => {
    mockApi({});
    render(
      <PurchaseOfferView
        planId="verified_route"
        analysisId="ana_123"
        tripId={null}
        priceAud={29}
        mode="demo"
        paid={purchase({ status: "paid", paid_at: "2026-10-10T03:00:00Z" })}
      />,
    );
    expect(screen.getByText("Purchased")).toBeInTheDocument();
    expect(screen.getByText(/A\$29 recorded against this analysis on 2026-10-10/)).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("demo checkout page", () => {
  it("is labelled as a demo, shows what is being bought, and confirms it", async () => {
    const server = mockApi({
      "GET /api/v1/billing/purchases/pur_1": { body: purchase() },
      "POST /api/v1/billing/purchases/pur_1/demo-confirm": {
        body: purchase({ status: "paid", paid_at: "2026-10-10T03:00:00Z" }),
      },
    });
    await renderDemoPage({ purchase: "pur_1" });

    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(screen.getByRole("heading", { level: 1, name: "Demo checkout" })).toBeInTheDocument();
    expect(screen.getByText("Demo · no card, no charge")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Loading the purchase…");

    const confirm = await screen.findByRole("button", { name: "Confirm demo purchase" });
    expect(screen.getByText("Verified Regional Route")).toBeInTheDocument();
    expect(screen.getByText("A$29")).toBeInTheDocument();
    expect(screen.getByText("No money moves.")).toBeInTheDocument();

    fireEvent.click(confirm);

    expect(await screen.findByText("Payment confirmed")).toBeInTheDocument();
    expect(screen.getByText("Paid")).toBeInTheDocument();
    expect(screen.getByText(/no card was taken and nothing was charged/)).toBeInTheDocument();
    expect(server.callsTo("POST /api/v1/billing/purchases/pur_1/demo-confirm")).toHaveLength(1);

    // Nothing left to press, and the way back is to the analysis that was bought.
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to your analysis" })).toHaveAttribute(
      "href",
      "/where-next/result/ana_123",
    );
    expect(screen.getByRole("link", { name: "Open the trip workspace" })).toHaveAttribute("href", "/trip/trp_9");
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("cancels without charging and offers the way back", async () => {
    const server = mockApi({
      "GET /api/v1/billing/purchases/pur_2": {
        body: purchase({ id: "pur_2", plan_id: "route_check", plan_name: "RouteCheck", analysis_id: "ana_rc_1", trip_id: null }),
      },
      "POST /api/v1/billing/purchases/pur_2/cancel": {
        body: purchase({ id: "pur_2", plan_id: "route_check", plan_name: "RouteCheck", analysis_id: "ana_rc_1", trip_id: null, status: "cancelled" }),
      },
    });
    await renderDemoPage({ purchase: "pur_2" });

    fireEvent.click(await screen.findByRole("button", { name: "Cancel" }));

    expect(await screen.findByText("Checkout cancelled")).toBeInTheDocument();
    expect(screen.getByText(/Nothing was charged/)).toBeInTheDocument();
    expect(server.callsTo("POST /api/v1/billing/purchases/pur_2/demo-confirm")).toHaveLength(0);
    expect(screen.getByRole("link", { name: "Back to your analysis" })).toHaveAttribute(
      "href",
      "/route-check/result/ana_rc_1",
    );
  });

  it("shows an already-paid purchase as paid and does not offer to pay again", async () => {
    mockApi({
      "GET /api/v1/billing/purchases/pur_1": {
        body: purchase({ status: "paid", paid_at: "2026-10-09T10:00:00Z", analysis_id: null, trip_id: null }),
      },
    });
    await renderDemoPage({ purchase: "pur_1" });

    expect(await screen.findByText("Payment confirmed")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm demo purchase" })).not.toBeInTheDocument();
    // No analysis or trip on the purchase: the only way on is home.
    expect(screen.getByRole("link", { name: "Back to the start" })).toHaveAttribute("href", "/");
  });

  it("says so when the purchase id is unknown", async () => {
    mockApi({
      "GET /api/v1/billing/purchases/pur_nope": apiError(404, "Purchase pur_nope not found", "not_found"),
    });
    await renderDemoPage({ purchase: "pur_nope" });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That purchase doesn't exist");
    expect(alert).toHaveTextContent("Nothing was charged");
    expect(screen.queryByRole("button", { name: "Confirm demo purchase" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Try again" })).not.toBeInTheDocument();
  });

  it("says so when the address carries no purchase id, without calling the API", async () => {
    const server = mockApi({});
    await renderDemoPage({});

    expect(screen.getByRole("alert")).toHaveTextContent("No purchase to show");
    expect(server.calls).toHaveLength(0);
  });

  it("offers a retry when the API is down, and recovers when it comes back", async () => {
    mockApiDown();
    await renderDemoPage({ purchase: "pur_1" });

    expect(await screen.findByRole("alert")).toHaveTextContent(/Could not reach the payment service/);

    mockApi({ "GET /api/v1/billing/purchases/pur_1": { body: purchase() } });
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(await screen.findByRole("button", { name: "Confirm demo purchase" })).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("keeps the purchase on screen and reports the reason when confirming fails", async () => {
    mockApi({
      "GET /api/v1/billing/purchases/pur_1": { body: purchase() },
      "POST /api/v1/billing/purchases/pur_1/demo-confirm": apiError(429, "Too many requests. Slow down."),
    });
    await renderDemoPage({ purchase: "pur_1" });

    fireEvent.click(await screen.findByRole("button", { name: "Confirm demo purchase" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Too many requests. Slow down.");
    expect(screen.queryByText("Payment confirmed")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm demo purchase" })).toBeEnabled();
  });

  it("refuses to confirm a card payment from the demo page", async () => {
    mockApi({
      "GET /api/v1/billing/purchases/pur_3": { body: purchase({ id: "pur_3", provider: "stripe", is_demo: false }) },
    });
    await renderDemoPage({ purchase: "pur_3" });

    expect(await screen.findByText("This is a card payment, not a demo purchase")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Confirm demo purchase" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Check the payment status" })).toHaveAttribute(
      "href",
      "/checkout/return?purchase=pur_3",
    );
  });
});

describe("checkout return page", () => {
  const stripe = (overrides: Partial<Purchase> = {}) =>
    purchase({ id: "pur_s", provider: "stripe", is_demo: false, ...overrides });

  it("asks the API to settle the payment and shows it as paid", async () => {
    const server = mockApi({
      "POST /api/v1/billing/purchases/pur_s/sync": { body: stripe({ status: "paid", paid_at: "2026-10-10T03:00:00Z" }) },
    });
    await renderReturnPage({ purchase: "pur_s" });

    expect(screen.getByRole("heading", { level: 1, name: "Your payment" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Confirming your payment…");

    expect(await screen.findByText("Payment confirmed")).toBeInTheDocument();
    expect(screen.getByText(/A\$29 was paid for Verified Regional Route/)).toBeInTheDocument();
    expect(screen.queryByText(/Demo/)).not.toBeInTheDocument();
    expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual(["POST /api/v1/billing/purchases/pur_s/sync"]);
    expect(screen.getByRole("link", { name: "Back to your analysis" })).toHaveAttribute(
      "href",
      "/where-next/result/ana_123",
    );
  });

  it("cancels, rather than syncs, when Stripe sends the traveller back with cancelled=1", async () => {
    const server = mockApi({
      "POST /api/v1/billing/purchases/pur_s/cancel": { body: stripe({ status: "cancelled" }) },
    });
    await renderReturnPage({ purchase: "pur_s", cancelled: "1" });

    expect(screen.getByRole("heading", { level: 1, name: "Checkout cancelled" })).toBeInTheDocument();
    expect(await screen.findByText("Cancelled")).toBeInTheDocument();
    expect(screen.getByText(/Nothing was charged/)).toBeInTheDocument();
    expect(server.calls.map((c) => `${c.method} ${c.path}`)).toEqual(["POST /api/v1/billing/purchases/pur_s/cancel"]);
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
  });

  it("does not claim a payment Stripe has not confirmed, and lets the traveller check again", async () => {
    let status = "pending";
    const server = mockApi({
      "POST /api/v1/billing/purchases/pur_s/sync": () => ({ body: stripe({ status }) }),
    });
    await renderReturnPage({ purchase: "pur_s" });

    expect(await screen.findByText("Payment not confirmed yet")).toBeInTheDocument();
    expect(screen.queryByText("Payment confirmed")).not.toBeInTheDocument();

    status = "paid";
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));

    expect(await screen.findByText("Payment confirmed")).toBeInTheDocument();
    expect(server.calls).toHaveLength(2);
  });

  it("offers a retry when Stripe cannot be asked, without claiming a payment", async () => {
    mockApi({
      "POST /api/v1/billing/purchases/pur_s/sync": apiError(502, "Stripe could not confirm the payment. Try again shortly."),
    });
    await renderReturnPage({ purchase: "pur_s" });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Stripe could not confirm the payment.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
    expect(screen.queryByText("Payment confirmed")).not.toBeInTheDocument();
  });
});
