# ADR 0010 — ECS Fargate on AWS, not Kubernetes

**Status:** accepted · **Date:** 2026-09-06

## Context

Two stateless services (API, web), a PostgreSQL database, a Redis cache and an
object store. It needs rolling deploys, autoscaling, secret injection, logs and
alarms.

## Decision

ECS Fargate behind an ALB. RDS PostgreSQL 16 with pgvector. ElastiCache Redis.
S3 with versioning for ingested source artefacts. Secrets Manager injected at
container start. CloudWatch logs, alarms and a dashboard. All Terraform, in
`infra/terraform/`.

Migrations and seeding run in the container entrypoint; both are idempotent, so a
fresh environment comes up usable.

Deploys use the ECS deployment circuit breaker with rollback: a task that never
passes its health check rolls back automatically rather than draining the
service.

## Alternatives considered

**EKS / Kubernetes.** Rejected explicitly. Two services and a database do not
justify a control plane to run, upgrade and secure. Fargate gives the same
rolling deploys and autoscaling with a fraction of the operational surface.
Adding Kubernetes here would be a CV keyword, not an engineering decision.

**Lambda.** Tempting for the API. Rejected: an analysis takes seconds and holds a
database connection; cold starts on a Python image with LangChain are poor; and
the MCP session is a persistent in-process object that fits badly in a
request-scoped runtime.

**App Runner.** Genuinely close, and simpler. Rejected for less control over
networking — the API needs to sit in private subnets with egress to providers but
no public address, which App Runner makes awkward.

**A managed vector database.** See ADR 0004.

## Consequences

Good: no cluster to operate, per-service autoscaling, automatic rollback,
secrets never in a task definition or a build log, and a reproducible environment
from one `terraform apply`.

Bad: Fargate costs more per vCPU-hour than EC2 at steady load, and cold-start on
a scale-out event is slower than Lambda. Both are the right trade at this scale.

HTTPS is opt-in via `certificate_arn`. Without it the ALB serves HTTP — fine for
a scratch environment, and stated in the README as unacceptable for production.
