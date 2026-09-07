variable "project_name" {
  description = "Short project slug used in resource names."
  type        = string
  default     = "jst"
}

variable "environment" {
  description = "Deployment environment. Drives multi-AZ, backups and deletion protection."
  type        = string
  default     = "staging"
  validation {
    condition     = contains(["staging", "production"], var.environment)
    error_message = "environment must be staging or production."
  }
}

variable "aws_region" {
  description = "AWS region. ap-southeast-2 keeps latency low for the Australian audience this is aimed at."
  type        = string
  default     = "ap-southeast-2"
}

variable "vpc_cidr" {
  type    = string
  default = "10.40.0.0/16"
}

# -- images -----------------------------------------------------------------
variable "image_tag" {
  description = "Immutable image tag to deploy, normally the git SHA."
  type        = string
  default     = "latest"
}

# -- sizing -----------------------------------------------------------------
variable "api_cpu" {
  type    = number
  default = 1024
}

variable "api_memory" {
  type    = number
  default = 2048
}

variable "web_cpu" {
  type    = number
  default = 512
}

variable "web_memory" {
  type    = number
  default = 1024
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "api_max_count" {
  type    = number
  default = 6
}

variable "web_desired_count" {
  type    = number
  default = 2
}

variable "db_instance_class" {
  description = "db.t4g.medium is enough for the MVP; vector search on a corpus this size is not the bottleneck."
  type        = string
  default     = "db.t4g.medium"
}

variable "db_allocated_storage" {
  type    = number
  default = 50
}

variable "db_max_allocated_storage" {
  type    = number
  default = 200
}

variable "postgres_version" {
  description = "pgvector is available as an extension from 15.2 onwards."
  type        = string
  default     = "16.4"
}

variable "cache_node_type" {
  type    = string
  default = "cache.t4g.micro"
}

# -- application ------------------------------------------------------------
variable "web_origin" {
  description = "Browser origin allowed by CORS. Must be the real public URL in production."
  type        = string
  default     = "http://localhost:3000"
}

variable "public_api_url" {
  description = "API base URL as the browser sees it."
  type        = string
  default     = "http://localhost:8000"
}

variable "certificate_arn" {
  description = "ACM certificate for HTTPS. Empty means HTTP only — acceptable for a scratch environment, never for production."
  type        = string
  default     = ""
}

variable "llm_provider" {
  description = "demo | openai | anthropic. Demo needs no credentials and the whole product still works."
  type        = string
  default     = "demo"
}

variable "embedding_provider" {
  type    = string
  default = "demo"
}

variable "place_provider" {
  type    = string
  default = "demo"
}

variable "transport_provider" {
  type    = string
  default = "demo"
}

variable "weather_provider" {
  type    = string
  default = "demo"
}

variable "run_seed" {
  description = "Seed the demo catalogue on container start. Idempotent."
  type        = bool
  default     = true
}

variable "otel_enabled" {
  type    = bool
  default = false
}

variable "log_level" {
  type    = string
  default = "INFO"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

variable "alert_email" {
  description = "Optional email for CloudWatch alarms."
  type        = string
  default     = ""
}
