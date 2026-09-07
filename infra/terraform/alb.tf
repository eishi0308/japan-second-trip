# ---------------------------------------------------------------------------
# Application Load Balancer
#
# One listener, two target groups. `/api/*`, `/health`, `/ready`, `/pricing`,
# `/providers` and `/docs` route to the API; everything else to the web app.
# ---------------------------------------------------------------------------
resource "aws_lb" "main" {
  name               = local.name
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]

  enable_deletion_protection = var.environment == "production"
  idle_timeout               = 120 # an analysis can legitimately take a while
  drop_invalid_header_fields = true
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

resource "aws_lb_target_group" "web" {
  name        = "${local.name}-web"
  port        = 3000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"

  health_check {
    path                = "/"
    matcher             = "200-399"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }

  deregistration_delay = 30
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.main.arn
  port              = 80
  protocol          = "HTTP"

  # With a certificate configured, plain HTTP only ever redirects.
  dynamic "default_action" {
    for_each = var.certificate_arn == "" ? [1] : []
    content {
      type             = "forward"
      target_group_arn = aws_lb_target_group.web.arn
    }
  }

  dynamic "default_action" {
    for_each = var.certificate_arn == "" ? [] : [1]
    content {
      type = "redirect"
      redirect {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count             = var.certificate_arn == "" ? 0 : 1
  load_balancer_arn = aws_lb.main.arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.web.arn
  }
}

locals {
  api_path_patterns = ["/api/*", "/health", "/ready", "/pricing", "/providers", "/docs", "/openapi.json"]
  listener_arn      = var.certificate_arn == "" ? aws_lb_listener.http.arn : aws_lb_listener.https[0].arn
}

resource "aws_lb_listener_rule" "api" {
  listener_arn = local.listener_arn
  priority     = 100

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }

  condition {
    path_pattern {
      values = local.api_path_patterns
    }
  }
}
