#!/usr/bin/env bash
# Build, push and roll out to AWS ECS.
#
# Assumes Terraform has already created the cluster, services and repositories,
# and that AWS credentials are present (CI assumes a role via OIDC).
set -euo pipefail

cd "$(dirname "$0")/.."

: "${AWS_REGION:?set AWS_REGION}"
PROJECT=${PROJECT_NAME:-jst}
ENVIRONMENT=${ENVIRONMENT:-staging}
NAME="${PROJECT}-${ENVIRONMENT}"
IMAGE_TAG=${IMAGE_TAG:-$(git rev-parse --short HEAD)}
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REGISTRY="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo "==> deploying ${NAME} at ${IMAGE_TAG}"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

echo "==> building images"
docker build -f apps/api/Dockerfile -t "${REGISTRY}/${NAME}-api:${IMAGE_TAG}" .
docker build -f apps/web/Dockerfile \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=${PUBLIC_API_URL:-http://localhost:8000}" \
  -t "${REGISTRY}/${NAME}-web:${IMAGE_TAG}" .

echo "==> pushing"
docker push "${REGISTRY}/${NAME}-api:${IMAGE_TAG}"
docker push "${REGISTRY}/${NAME}-web:${IMAGE_TAG}"

echo "==> rolling the services"
# The task definition pins an immutable tag, so a deploy is a new revision.
for service in api web; do
  aws ecs update-service \
    --cluster "$NAME" \
    --service "${NAME}-${service}" \
    --force-new-deployment \
    --region "$AWS_REGION" >/dev/null
done

echo "==> waiting for the deployment to stabilise"
# ECS's circuit breaker rolls back automatically if the new tasks never pass
# their health checks, so this either succeeds or leaves the old version serving.
aws ecs wait services-stable \
  --cluster "$NAME" \
  --services "${NAME}-api" "${NAME}-web" \
  --region "$AWS_REGION"

echo "==> deployed ${IMAGE_TAG}"
