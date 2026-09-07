# travel-intelligence-mcp

A real MCP server exposing verified travel intelligence to multiple AI
consumers. Not a README demo — it is the only route the agents have to any
external capability.

## Why it exists

Three consumers need the same capabilities with **different permissions**.
Without a boundary, each grows its own copy of "search evidence" and "get
transport", and the permission differences end up wherever someone last edited.

| Consumer | Tools | May write trip state | Why |
| --- | --- | --- | --- |
| WhereNext agent | 13 | **yes** | it produces the candidate and the rejections |
| RouteCheck agent | 12 | no | critiquing an itinerary is not a reason to write |
| Admin verification assistant | 7 | no | acts for a reviewer, never for a traveller |

That asymmetry is also the capability half of the injection defence: a persuaded
model cannot reach a write tool the consumer does not hold.

## Architectural boundary

The package owns the **interface** — tool list, JSON schemas, argument
validation, error shaping — and none of the implementation. Everything behind a
tool arrives through the `TravelBackend` protocol, which is why
`packages/travel_mcp` has no database, provider or application imports and can be
tested with a fake backend.

**What does not go through MCP:** ordinary internal CRUD. Trip creation,
analysis persistence and evidence-by-id are direct repository calls. Routing them
through JSON-RPC would add serialisation and a failure mode for nothing.

## Transports

**In-process** (the API): a real `ClientSession` over in-memory streams. Full
JSON-RPC — initialise, `tools/list`, `tools/call`. Argument validation and
output-schema validation are the protocol's, not a wrapper's, so a tool call from
WhereNext takes exactly the same path as one from an external client.

**stdio** (external clients):

```bash
travel-intelligence-mcp
```

```json
{
  "mcpServers": {
    "travel-intelligence": {
      "command": "travel-intelligence-mcp",
      "env": { "DATABASE_URL": "postgresql+asyncpg://jst:jst@localhost:5433/jst" }
    }
  }
}
```

## Tools

### Evidence
- `search_verified_evidence` — hybrid search with metadata filters, reranking and
  citation-preserving results
- `get_source_evidence` — specific chunks and their full text by id

### Places
- `get_place_details` — resolve free text to a catalogue entry
- `get_place_constraints` — booking and access constraints, plus evidence

### Transport
- `search_transport` — options between two places, verified records preferred
- `get_route_context` — a whole itinerary's legs in one call
- `calculate_travel_load` — deterministic load metrics, no model involved
- `check_route_constraints` — the rules engine, returning graded issues with the
  measurements that triggered them

### Booking and weather
- `get_booking_requirements`
- `get_weather_context` — context only, never a constraint

### Verification and HITL
- `get_verification_status` — records, freshness, detected conflicts
- `create_human_review_request` — escalate; idempotent, and an existing task
  adopts the analysis it now blocks

### Trip state
- `get_trip_context` — persistent memory
- `save_trip_decision` — the only write tool in the gateway

## Guarantees

- **Typed both ways.** Every tool publishes an input *and* an output schema.
  Contracts live once, in `shared_schemas`, and both the server and every
  consumer validate against them.
- **Flat schemas.** Parameters are top-level (`from_place`, `to_place`), not
  wrapped in an `args` object — an LLM planning a call should see the fields.
- **Bad arguments are rejected before dispatch**, by the protocol layer.
- **No model-generated facts.** Durations come from verified records, a live
  provider, or a clearly-labelled geometric estimate. A hop with no public
  service returns the car option rather than an invented train.
- **Nothing can book, pay, cancel or contact anyone.**

## Testing

`apps/backend/tests/integration/test_mcp.py` — 16 tests over a real session: schema
publication, flat parameters, argument rejection, unknown-tool rejection,
verified-over-estimate preference, the car-only hop, permission enforcement,
budget enforcement, and trip-state round-tripping.
