import type { PaidPlanId, Purchase } from "./types";

/** Display names for the two plans that can be bought. Prices are never kept here — they come from the API. */
export const PLAN_NAMES: Record<PaidPlanId, string> = {
  verified_route: "Verified Regional Route",
  route_check: "RouteCheck",
};

export const formatAud = (amount: number) => `A$${amount}`;

/** The result page a purchase was made from, when it was made from one. */
export function analysisHref(purchase: Pick<Purchase, "plan_id" | "analysis_id">): string | null {
  if (!purchase.analysis_id) return null;
  if (purchase.plan_id === "verified_route") return `/where-next/result/${purchase.analysis_id}`;
  if (purchase.plan_id === "route_check") return `/route-check/result/${purchase.analysis_id}`;
  return null;
}

export function tripHref(purchase: Pick<Purchase, "trip_id">): string | null {
  return purchase.trip_id ? `/trip/${purchase.trip_id}` : null;
}
