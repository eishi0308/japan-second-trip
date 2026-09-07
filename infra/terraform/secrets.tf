# ---------------------------------------------------------------------------
# Secrets
#
# Nothing sensitive is passed as a plain task environment variable. Secrets
# Manager entries are injected by the ECS agent at container start, so they
# never appear in a task definition, a build log, or `docker inspect`.
# ---------------------------------------------------------------------------
resource "aws_secretsmanager_secret" "database_url" {
  name                    = "${local.name}/database-url"
  recovery_window_in_days = var.environment == "production" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "database_url" {
  secret_id = aws_secretsmanager_secret.database_url.id
  secret_string = format(
    "postgresql+asyncpg://%s:%s@%s/%s",
    aws_db_instance.main.username,
    urlencode(random_password.database.result),
    aws_db_instance.main.endpoint,
    aws_db_instance.main.db_name,
  )
}

resource "aws_secretsmanager_secret" "redis_url" {
  name                    = "${local.name}/redis-url"
  recovery_window_in_days = var.environment == "production" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "redis_url" {
  secret_id     = aws_secretsmanager_secret.redis_url.id
  secret_string = "redis://${aws_elasticache_replication_group.main.primary_endpoint_address}:6379/0"
}

resource "random_password" "admin_token" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "admin_token" {
  name                    = "${local.name}/admin-token"
  recovery_window_in_days = var.environment == "production" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "admin_token" {
  secret_id     = aws_secretsmanager_secret.admin_token.id
  secret_string = random_password.admin_token.result
}

resource "random_password" "jwt_secret" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "jwt_secret" {
  name                    = "${local.name}/jwt-secret"
  recovery_window_in_days = var.environment == "production" ? 30 : 0
}

resource "aws_secretsmanager_secret_version" "jwt_secret" {
  secret_id     = aws_secretsmanager_secret.jwt_secret.id
  secret_string = random_password.jwt_secret.result
}

# Provider API keys are created empty by Terraform and populated out of band.
# Terraform state should never contain a third-party credential.
resource "aws_secretsmanager_secret" "provider_keys" {
  for_each = toset(["openai-api-key", "anthropic-api-key", "google-maps-api-key"])

  name                    = "${local.name}/${each.key}"
  recovery_window_in_days = var.environment == "production" ? 30 : 0
  description             = "Populate manually or via CI; intentionally not managed in state."
}
