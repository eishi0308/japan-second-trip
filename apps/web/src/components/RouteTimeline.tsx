import type { RouteCheckResult } from "@/lib/types";
import { Badge } from "./primitives";

/**
 * The route as a vertical timeline: stops with their nights, hops with their
 * real durations. Estimated hops are marked, because "3h10 verified" and
 * "about 3h, estimated from distance" are different promises.
 */
export function RouteTimeline({ route }: { route: NonNullable<RouteCheckResult["parsed_route"]> }) {
  const segmentsFrom = new Map(route.segments.map((s) => [s.from_order, s]));

  return (
    <ol className="relative">
      {route.stops.map((stop, index) => {
        const segment = segmentsFrom.get(stop.order);
        const isLast = index === route.stops.length - 1;
        return (
          <li key={`${stop.order}-${stop.raw_name}`} className="relative pl-8">
            {!isLast ? (
              <span aria-hidden="true" className="absolute left-[0.3rem] top-3 h-full w-px bg-ink-200" />
            ) : null}
            <span
              aria-hidden="true"
              className={`absolute left-0 top-2 h-2.5 w-2.5 rounded-full ${
                stop.resolved ? "bg-ink-900" : "border-2 border-signal-warning bg-paper"
              }`}
            />
            <div className="pb-1">
              <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
                <span className="font-serif text-[1.05rem] text-ink-900">
                  {stop.display_name ?? stop.raw_name}
                </span>
                {stop.nights > 0 ? (
                  <span className="text-[0.82rem] tabular-nums text-ink-600">
                    {stop.nights} night{stop.nights === 1 ? "" : "s"}
                  </span>
                ) : (
                  <span className="text-[0.82rem] text-ink-500">pass through</span>
                )}
                {!stop.resolved ? <Badge tone="warning">not identified</Badge> : null}
              </div>
              {stop.resolution_note ? (
                <p className="mt-0.5 text-[0.78rem] text-ink-500">{stop.resolution_note}</p>
              ) : null}
            </div>

            {segment ? (
              <div className="my-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-ink-50 px-3 py-2 text-[0.8rem] text-ink-600">
                <span className="tabular-nums font-medium text-ink-800">
                  {(segment.duration_minutes / 60).toFixed(1)}h
                </span>
                <span>{segment.mode.replace(/_/g, " ")}</span>
                <span>
                  {segment.transfers} transfer{segment.transfers === 1 ? "" : "s"}
                </span>
                {segment.requires_car ? <Badge tone="critical">car required</Badge> : null}
                {segment.is_estimate ? <Badge tone="warning">estimated</Badge> : null}
                {segment.last_departure_local ? (
                  <span className="text-ink-500">last connection {segment.last_departure_local}</span>
                ) : null}
              </div>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
