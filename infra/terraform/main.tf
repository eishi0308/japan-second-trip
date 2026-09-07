# Japan Second Trip — MVP deployment on AWS.
#
# Shape: ECS Fargate behind an ALB, RDS PostgreSQL with pgvector, ElastiCache
# Redis, secrets in Secrets Manager, logs and alarms in CloudWatch.
#
# Deliberately NOT Kubernetes. Two stateless services and a database do not
# justify a control plane; Fargate gives the same rolling deploys and autoscaling
# with a fraction of the operational surface. See docs/adr/0010-aws-deployment.md.

terraform {
  required_version = ">= 1.7"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.60" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }

  # Configure with -backend-config; not committed, because state contains
  # resource identifiers that should not be in a public repository.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "japan-second-trip"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name = "${var.project_name}-${var.environment}"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)

  # The API needs egress (LLM and mapping providers) but must not be publicly
  # addressable; it sits in private subnets behind the load balancer.
  container_env = [
    { name = "ENVIRONMENT", value = var.environment },
    { name = "LOG_JSON", value = "true" },
    { name = "LOG_LEVEL", value = var.log_level },
    { name = "CORS_ORIGINS", value = var.web_origin },
    { name = "LLM_PROVIDER", value = var.llm_provider },
    { name = "EMBEDDING_PROVIDER", value = var.embedding_provider },
    { name = "PLACE_PROVIDER", value = var.place_provider },
    { name = "TRANSPORT_PROVIDER", value = var.transport_provider },
    { name = "WEATHER_PROVIDER", value = var.weather_provider },
    { name = "OTEL_ENABLED", value = tostring(var.otel_enabled) },
    { name = "RUN_MIGRATIONS", value = "true" },
    { name = "RUN_SEED", value = tostring(var.run_seed) },
  ]
}

# ---------------------------------------------------------------------------
# Networking
# ---------------------------------------------------------------------------
resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = local.name }
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.name}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
  availability_zone = local.azs[count.index]
  tags              = { Name = "${local.name}-private-${count.index}" }
}

resource "aws_eip" "nat" {
  domain = "vpc"
  tags   = { Name = "${local.name}-nat" }
}

resource "aws_nat_gateway" "main" {
  allocation_id = aws_eip.nat.id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.main]
  tags          = { Name = local.name }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
  tags = { Name = "${local.name}-public" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main.id
  }
  tags = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# ---------------------------------------------------------------------------
# Security groups — least privilege, each tier reachable only from the one above
# ---------------------------------------------------------------------------
resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Public ingress to the load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description = "HTTPS from the internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP, redirected to HTTPS"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "service" {
  name        = "${local.name}-service"
  description = "ECS tasks; reachable only from the load balancer"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "API from the ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  ingress {
    description     = "Web from the ALB"
    from_port       = 3000
    to_port         = 3000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Outbound to AWS services and external providers"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "database" {
  name        = "${local.name}-database"
  description = "PostgreSQL; reachable only from the ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "PostgreSQL from the service tier"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }
}

resource "aws_security_group" "cache" {
  name        = "${local.name}-cache"
  description = "Redis; reachable only from the ECS tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "Redis from the service tier"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.service.id]
  }
}
