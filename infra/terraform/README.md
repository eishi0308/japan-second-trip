# Terraform — AWS deployment

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # then edit

terraform init \
  -backend-config="bucket=YOUR-STATE-BUCKET" \
  -backend-config="key=japan-second-trip/staging.tfstate" \
  -backend-config="region=ap-southeast-2"

terraform plan
terraform apply
```

Then push images and roll the services:

```bash
IMAGE_TAG=$(git rev-parse --short HEAD) ./scripts/deploy.sh
```

## What this creates

| Layer | Resource | Why |
| --- | --- | --- |
| Compute | ECS Fargate, 2 services | Rolling deploys and autoscaling without a control plane to run |
| Ingress | ALB, path-routed | `/api/*`, `/health`, `/ready` → API; everything else → web |
| Database | RDS PostgreSQL 16 + pgvector | Relational travel data and vector evidence in one transaction boundary |
| Cache | ElastiCache Redis | Provider/retrieval cache and the shared rate-limit counter |
| Objects | S3, versioned | Raw ingested sources — versioning is what source-change detection diffs against |
| Secrets | Secrets Manager | Injected at container start; never in a task definition or a build log |
| Observability | CloudWatch logs, alarms, dashboard | Latency, 5xx, healthy hosts, database headroom, HITL escalation rate |

## Deliberate omissions

* **No Kubernetes.** Two stateless services and a database do not justify it.
* **No separate vector database.** See `docs/adr/0004-postgres-pgvector.md`.
* **Provider API keys are not in state.** Terraform creates the secret *containers*;
  the values are populated out of band so a credential never lands in a state file.
* **HTTPS is opt-in via `certificate_arn`.** Without it the ALB serves HTTP, which
  is fine for a scratch environment and not acceptable for production.
