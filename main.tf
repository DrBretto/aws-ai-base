terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

# Configure the AWS Provider
provider "aws" {
  region  = "us-east-1"
  profile = "personal"
}

# Reference the existing S3 bucket
data "aws_s3_bucket" "tiingo_data_bucket" {
  bucket = "aws-ai-base-bucket"
}

# IAM Role for Lambda functions
resource "aws_iam_role" "lambda_exec_role" {
  name = "aws-ai-base-lambda-exec-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })
}

# IAM Policy for Lambda execution (logging)
resource "aws_iam_policy" "lambda_logging_policy" {
  name        = "aws-ai-base-lambda-logging-policy"
  description = "IAM policy for Lambda logging"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
        Effect = "Allow"
      },
    ]
  })
}

# Attach logging policy to the Lambda execution role
resource "aws_iam_role_policy_attachment" "lambda_logging_attach" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_logging_policy.arn
}

# IAM Policy for S3 access (for tiingoScraper and backfillOrchestrator)
resource "aws_iam_policy" "s3_access_policy" {
  name        = "aws-ai-base-s3-access-policy"
  description = "IAM policy for S3 access"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:PutObject",
          "s3:PutObjectAcl",
          "s3:GetObject",
          "s3:DeleteObject"
        ]
        Resource = "${data.aws_s3_bucket.tiingo_data_bucket.arn}/*"
        Effect = "Allow"
      },
    ]
  })
}

# Attach S3 access policy to the Lambda execution role
resource "aws_iam_role_policy_attachment" "s3_access_attach" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.s3_access_policy.arn
}

# IAM Policy for Lambda invocation (for backfillOrchestrator to invoke tiingoScraper)
resource "aws_iam_policy" "lambda_invoke_policy" {
  name        = "aws-ai-base-lambda-invoke-policy"
  description = "IAM policy for Lambda invocation"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = aws_lambda_function.tiingo_scraper_lambda.arn
        Effect = "Allow"
      },
    ]
  })
}

# Attach Lambda invocation policy to the Lambda execution role
resource "aws_iam_role_policy_attachment" "lambda_invoke_attach" {
  role       = aws_iam_role.lambda_exec_role.name
  policy_arn = aws_iam_policy.lambda_invoke_policy.arn
}

# Tiingo Scraper Lambda Function (Docker image)
resource "aws_lambda_function" "tiingo_scraper_lambda" {
  function_name = "tiingo-price-scraper"
  package_type  = "Image"
  image_uri     = var.tiingo_scraper_image_uri

  role    = aws_iam_role.lambda_exec_role.arn
  timeout = 900
  memory_size = 256

  environment {
    variables = {
      TIINGO_API_KEY = "b2ecb7b12c6c181c3637017d7d47180ba2c0225a"
      S3_BUCKET_NAME = data.aws_s3_bucket.tiingo_data_bucket.bucket
    }
  }
}

# Backfill Orchestrator Lambda Function (Docker image)
resource "aws_lambda_function" "backfill_orchestrator_lambda" {
  function_name = "tiingo-backfill-orchestrator"
  package_type  = "Image"
  image_uri     = var.backfill_orchestrator_image_uri

  role    = aws_iam_role.lambda_exec_role.arn
  timeout = 900
  memory_size = 128

  environment {
    variables = {
      SCRAPER_LAMBDA_NAME = aws_lambda_function.tiingo_scraper_lambda.function_name
      S3_BUCKET_NAME      = data.aws_s3_bucket.tiingo_data_bucket.bucket
    }
  }
}

# EventBridge Rule for daily trigger at 2 AM for scraper
resource "aws_cloudwatch_event_rule" "daily_tiingo_scraper_schedule" {
  name                = "daily-tiingo-scraper-schedule"
  description         = "Triggers the Tiingo price scraper Lambda daily at 2 AM"
  schedule_expression = "cron(0 2 * * ? *)"
  tags = {
    ManagedBy = "Terraform"
  }
}

# EventBridge Target to invoke the scraper Lambda daily
resource "aws_cloudwatch_event_target" "tiingo_scraper_daily_target" {
  rule      = aws_cloudwatch_event_rule.daily_tiingo_scraper_schedule.name
  target_id = "InvokeTiingoScraperLambdaDaily"
  arn       = aws_lambda_function.tiingo_scraper_lambda.arn
  input     = jsonencode({"type": "daily"})
}

# Lambda Permission for EventBridge to invoke the scraper Lambda daily
resource "aws_lambda_permission" "allow_eventbridge_to_invoke_tiingo_scraper_daily" {
  statement_id  = "AllowExecutionFromEventBridgeDaily"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tiingo_scraper_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_tiingo_scraper_schedule.arn
}

# EventBridge Rule for hourly trigger for backfill orchestrator
resource "aws_cloudwatch_event_rule" "hourly_backfill_orchestrator_schedule" {
  name                = "hourly-backfill-orchestrator-schedule"
  description         = "Triggers the Tiingo backfill orchestrator Lambda hourly"
  schedule_expression = "cron(0 * * * ? *)"
  tags = {
    ManagedBy = "Terraform"
  }
}

# EventBridge Target to invoke the backfill orchestrator Lambda hourly
resource "aws_cloudwatch_event_target" "backfill_orchestrator_hourly_target" {
  rule      = aws_cloudwatch_event_rule.hourly_backfill_orchestrator_schedule.name
  target_id = "InvokeBackfillOrchestratorLambdaHourly"
  arn       = aws_lambda_function.backfill_orchestrator_lambda.arn
  input     = jsonencode({})
}

# Lambda Permission for EventBridge to invoke the backfill orchestrator Lambda hourly
resource "aws_lambda_permission" "allow_eventbridge_to_invoke_backfill_orchestrator_hourly" {
  statement_id  = "AllowExecutionFromEventBridgeHourly"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.backfill_orchestrator_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly_backfill_orchestrator_schedule.arn
}