output "application_url" {
  description = "Public entry point."
  value       = var.certificate_arn == "" ? "http://${aws_lb.main.dns_name}" : "https://${aws_lb.main.dns_name}"
}

output "api_health_url" {
  value = "http://${aws_lb.main.dns_name}/health"
}

output "api_repository_url" {
  value = aws_ecr_repository.api.repository_url
}

output "web_repository_url" {
  value = aws_ecr_repository.web.repository_url
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "api_service_name" {
  value = aws_ecs_service.api.name
}

output "web_service_name" {
  value = aws_ecs_service.web.name
}

output "database_endpoint" {
  value     = aws_db_instance.main.endpoint
  sensitive = true
}

output "admin_token_secret_arn" {
  description = "Read with: aws secretsmanager get-secret-value --secret-id <arn>"
  value       = aws_secretsmanager_secret.admin_token.arn
}

output "artifacts_bucket" {
  value = aws_s3_bucket.artifacts.bucket
}

output "dashboard_url" {
  value = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.main.dashboard_name}"
}
