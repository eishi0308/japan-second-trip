# ---------------------------------------------------------------------------
# PostgreSQL with pgvector
#
# pgvector ships with RDS PostgreSQL 15.2+ as an available extension; the
# migration issues CREATE EXTENSION on first run. No self-managed database and
# no separate vector service: the whole point of the data-model decision is that
# relational travel data and vector evidence live in one operational database
# with one transaction boundary. See docs/adr/0004-postgres-pgvector.md.
# ---------------------------------------------------------------------------
resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "random_password" "database" {
  length           = 32
  special          = true
  override_special = "!#$%&*()-_=+[]{}<>:?"
}

resource "aws_db_parameter_group" "postgres" {
  name   = "${local.name}-pg16"
  family = "postgres16"

  parameter {
    name         = "shared_preload_libraries"
    value        = "pg_stat_statements"
    apply_method = "pending-reboot"
  }

  # Surface slow retrieval queries rather than guessing about them.
  parameter {
    name  = "log_min_duration_statement"
    value = "500"
  }
}

resource "aws_db_instance" "main" {
  identifier     = local.name
  engine         = "postgres"
  engine_version = var.postgres_version
  instance_class = var.db_instance_class

  allocated_storage     = var.db_allocated_storage
  max_allocated_storage = var.db_max_allocated_storage
  storage_type          = "gp3"
  storage_encrypted     = true

  db_name  = "jst"
  username = "jst"
  password = random_password.database.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.database.id]
  parameter_group_name   = aws_db_parameter_group.postgres.name
  publicly_accessible    = false

  multi_az                = var.environment == "production"
  backup_retention_period = var.environment == "production" ? 14 : 3
  backup_window           = "16:00-17:00" # 02:00 Australia/Sydney
  maintenance_window      = "sun:17:00-sun:18:00"

  performance_insights_enabled    = true
  enabled_cloudwatch_logs_exports = ["postgresql"]

  auto_minor_version_upgrade = true
  deletion_protection        = var.environment == "production"
  skip_final_snapshot        = var.environment != "production"
  final_snapshot_identifier  = var.environment == "production" ? "${local.name}-final" : null

  apply_immediately = var.environment != "production"
}

# ---------------------------------------------------------------------------
# Redis — the cache and the rate limiter's shared counter
# ---------------------------------------------------------------------------
resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_replication_group" "main" {
  replication_group_id = local.name
  description          = "Cache and rate-limit counters for ${local.name}"
  engine               = "redis"
  engine_version       = "7.1"
  node_type            = var.cache_node_type
  num_cache_clusters   = var.environment == "production" ? 2 : 1
  port                 = 6379

  subnet_group_name          = aws_elasticache_subnet_group.main.name
  security_group_ids         = [aws_security_group.cache.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = false # in-VPC only; TLS adds latency to a cache

  automatic_failover_enabled = var.environment == "production"
  apply_immediately          = var.environment != "production"
}

# ---------------------------------------------------------------------------
# S3 — raw ingested source artefacts, kept for provenance and re-chunking
# ---------------------------------------------------------------------------
resource "aws_s3_bucket" "artifacts" {
  bucket        = "${local.name}-artifacts"
  force_destroy = var.environment != "production"
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  versioning_configuration {
    # Versioning is the point: when a source page changes, the previous fetch is
    # what the change-detection diff is against.
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = 180
    }
  }
}
