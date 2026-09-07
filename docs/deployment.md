# Deployment

## Local

```bash
make setup      # Python env + npm install
make dev        # database, API, web
```

Web on :3000, API on :8000, admin at /admin with `ADMIN_TOKEN`.

`make reset` drops and re-seeds. Everything runs on demo providers with no
credentials.

## Docker

```bash
docker compose up --build
```

Brings up PostgreSQL+pgvector, Redis, the API and the web app. The API entrypoint
applies migrations and seeds on start; both are idempotent.

```bash
curl localhost:8000/ready     # database, seed state, provider disclosure
```

## AWS

Terraform in `infra/terraform/`. See its README for the shape and the deliberate
omissions.

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # edit
terraform init -backend-config="bucket=…" -backend-config="key=…" -backend-config="region=ap-southeast-2"
terraform apply

IMAGE_TAG=$(git rev-parse --short HEAD) ./scripts/deploy.sh
```

`terraform validate` passes; the configuration has not been applied against a
live AWS account.

### Deploy safety

- images are tagged immutably with the git SHA
- ECS deployment circuit breaker with rollback: a task that never passes its
  health check rolls back rather than draining the service
- `deployment_minimum_healthy_percent = 100` — capacity never dips during a roll
- `aws ecs wait services-stable` blocks the pipeline until the rollout settles

### Migrations

Run in the container entrypoint before the server starts. Idempotent and
forward-only. For a destructive change, run the migration as a one-off ECS task
first and deploy afterwards.

## Configuration

Everything is environment-driven; `.env.example` documents every variable.

Values that **must** be set for a real deployment:

| Variable | Why |
| --- | --- |
| `ADMIN_TOKEN` | the development default is refused in staging/production |
| `JWT_SECRET` | signs trip capability tokens |
| `CORS_ORIGINS` | the default is localhost only |
| `DATABASE_URL` | injected from Secrets Manager |
| `certificate_arn` (Terraform) | without it the ALB serves plain HTTP |

## Going live with real providers

Demo mode is fully functional, so switch one capability at a time and watch the
evals:

1. `EMBEDDING_PROVIDER=openai` + `OPENAI_API_KEY`, then **re-ingest** — existing
   vectors were produced by a different embedder and cannot be compared with new
   ones. Re-run the retrieval eval and compare against the committed baseline.
2. `LLM_PROVIDER=anthropic|openai` + key. Run the agent and RAG evals; watch cost
   per run in `/admin/metrics`.
3. `PLACE_PROVIDER` / `TRANSPORT_PROVIDER` / `WEATHER_PROVIDER`. Verified seeded
   records still win over live lookups by design.
4. `RERANKER=llm` only if the eval shows it beats the heuristic on your corpus.

## Operations

`/health` is liveness and never touches the database. `/ready` verifies the
database is reachable *and* seeded, and discloses which providers are live.

Alarms: API 5xx, p95 latency > 8s, no healthy hosts, database CPU and free
storage. A log-derived metric tracks human-review escalations — a spike means the
corpus went stale or something upstream broke.

The admin console at `/admin` exposes the review queue, the agent-run inspector
(node path, tool calls with redacted arguments, cost), failed tool calls, stale
evidence and eval history.

## Cost

Rough monthly, ap-southeast-2, staging sizing:

| Item | Approx |
| --- | --- |
| ECS Fargate (2 API + 2 web) | US$70 |
| RDS db.t4g.medium | US$60 |
| ElastiCache t4g.micro | US$15 |
| ALB | US$20 |
| NAT gateway | US$35 |
| S3 + CloudWatch | US$10 |
| **Infrastructure** | **~US$210** |
| LLM (demo) | US$0 |
| LLM (live, ~5k tokens/analysis) | ~US$0.03/analysis with routing |

The NAT gateway is a meaningful share and could be replaced with VPC endpoints
for a single-region deployment.
