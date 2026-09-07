# ---------------------------------------------------------------------------
# CloudWatch alarms
#
# Alarms on what would actually hurt a user: the API failing, the API being
# slow, the database running out of headroom. Not on every metric that exists.
# ---------------------------------------------------------------------------
resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_Target_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "The API is returning server errors."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "api_latency" {
  alarm_name          = "${local.name}-api-p95-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 300
  extended_statistic  = "p95"
  threshold           = 8
  alarm_description   = "p95 latency above 8s — an analysis should not take this long."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "no_healthy_api" {
  alarm_name          = "${local.name}-api-no-healthy-hosts"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Minimum"
  threshold           = 1
  alarm_description   = "No healthy API tasks."
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "breaching"

  dimensions = {
    LoadBalancer = aws_lb.main.arn_suffix
    TargetGroup  = aws_lb_target_group.api.arn_suffix
  }
}

resource "aws_cloudwatch_metric_alarm" "database_cpu" {
  alarm_name          = "${local.name}-db-cpu"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "CPUUtilization"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Database CPU sustained above 80% — check retrieval query plans."
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }
}

resource "aws_cloudwatch_metric_alarm" "database_storage" {
  alarm_name          = "${local.name}-db-free-storage"
  comparison_operator = "LessThanThreshold"
  evaluation_periods  = 1
  metric_name         = "FreeStorageSpace"
  namespace           = "AWS/RDS"
  period              = 300
  statistic           = "Minimum"
  threshold           = 5 * 1024 * 1024 * 1024
  alarm_description   = "Less than 5 GB of database storage free."
  alarm_actions       = [aws_sns_topic.alerts.arn]

  dimensions = {
    DBInstanceIdentifier = aws_db_instance.main.id
  }
}

# A log-derived metric: guardrail escalations are a product signal, not just an
# error. A spike means either the corpus went stale or something upstream broke.
resource "aws_cloudwatch_log_metric_filter" "human_review_created" {
  name           = "${local.name}-human-review-created"
  log_group_name = aws_cloudwatch_log_group.api.name
  pattern        = "{ $.event = \"hitl.task_created\" }"

  metric_transformation {
    name      = "HumanReviewTasksCreated"
    namespace = "JapanSecondTrip"
    value     = "1"
    unit      = "Count"
  }
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = local.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", width = 12, height = 6, x = 0, y = 0
        properties = {
          title  = "API latency and errors"
          region = var.aws_region
          metrics = [
            ["AWS/ApplicationELB", "TargetResponseTime", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "p50" }],
            ["...", { stat = "p95" }],
            ["AWS/ApplicationELB", "HTTPCode_Target_5XX_Count", "LoadBalancer", aws_lb.main.arn_suffix, { stat = "Sum" }],
          ]
        }
      },
      {
        type = "metric", width = 12, height = 6, x = 12, y = 0
        properties = {
          title   = "Human review escalations"
          region  = var.aws_region
          metrics = [["JapanSecondTrip", "HumanReviewTasksCreated", { stat = "Sum" }]]
        }
      },
    ]
  })
}
