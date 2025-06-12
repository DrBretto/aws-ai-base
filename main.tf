terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

# Configure the AWS Provider
provider "aws" {
  region  = "us-east-1" # From .samconfig.toml and serverless.yml
  profile = "personal"  # From .samconfig.toml and serverless.yml
}

# Reference the existing S3 bucket
data "aws_s3_bucket" "tiingo_data_bucket" {
  bucket = "aws-ai-base-bucket" # From SAM template and serverless.yml
}

# Reference the existing requests layer
data "aws_lambda_layer_version" "requests_layer" {
  layer_name = "requests-layer" # Name of the layer I created
  version    = 1              # Version of the layer I created
}

# Package Hello World Lambda function code
data "archive_file" "hello_world_zip" {
  type        = "zip"
  source_dir  = "src/hello_world"
  output_path = "hello_world.zip"
}

# Package Tiingo Scraper Lambda function code
data "archive_file" "tiingo_scraper_lambda_zip" {
  type        = "zip"
  source_dir  = "src/tiingo_scraper_lambda"
  output_path = "tiingo_scraper_lambda.zip"
}

# Package Backfill Orchestrator Lambda function code
data "archive_file" "backfill_orchestrator_zip" {
  type        = "zip"
  source_dir  = "src/tiingo_scraper"
  output_path = "tiingo_scraper.zip"
}

# IAM Role for Lambda functions
resource "aws_iam_role" "lambda_exec_role" {
  name = "aws-ai-base-lambda-exec-role" # Descriptive name

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
        Resource = "arn:aws:logs:*:*:*" # Allow logging to any log group
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
          "s3:PutObjectAcl", # Needed for tiingoScraper
          "s3:GetObject",    # Needed for backfillOrchestrator
          "s3:DeleteObject"  # Needed for backfillOrchestrator
        ]
        Resource = "${data.aws_s3_bucket.tiingo_data_bucket.arn}/*" # Allow access to objects in the bucket
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
        Resource = aws_lambda_function.tiingo_scraper_lambda.arn # Allow invocation of the scraper function
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

# Hello World Lambda Function
resource "aws_lambda_function" "hello_world_lambda" {
  function_name = "AWS-AI-Base-helloWorld" # Match Serverless naming convention
  handler       = "app.lambda_handler"
  runtime       = "python3.12" # From serverless.yml
  filename      = data.archive_file.hello_world_zip.output_path # Use the zip file created by archive_file
  source_code_hash = data.archive_file.hello_world_zip.output_base64sha256 # Use the hash from archive_file

  role    = aws_iam_role.lambda_exec_role.arn
  timeout = 3 # From SAM Globals (Serverless default was higher)
  memory_size = 1024 # Serverless default for this function
}

# Tiingo Scraper Lambda Function
resource "aws_lambda_function" "tiingo_scraper_lambda" {
  function_name = "tiingo-price-scraper" # From serverless.yml
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.12" # From serverless.yml
  filename      = data.archive_file.tiingo_scraper_lambda_zip.output_path # Use the zip file created by archive_file
  source_code_hash = data.archive_file.tiingo_scraper_lambda_zip.output_base64sha256 # Use the hash from archive_file

  role    = aws_iam_role.lambda_exec_role.arn
  timeout = 900 # From serverless.yml
  memory_size = 256 # From serverless.yml

  environment {
    variables = {
      TIINGO_API_KEY = "b2ecb7b12c6c181c3637017d7d47180ba2c0225a" # From serverless.yml
      S3_BUCKET_NAME = data.aws_s3_bucket.tiingo_data_bucket.bucket # Reference the S3 bucket name
    }
  }

  layers = [data.aws_lambda_layer_version.requests_layer.arn] # Attach the requests layer
}

# Backfill Orchestrator Lambda Function
resource "aws_lambda_function" "backfill_orchestrator_lambda" {
  function_name = "tiingo-backfill-orchestrator" # From serverless.yml
  handler       = "backfill_orchestrator.lambda_handler"
  runtime       = "python3.12" # From serverless.yml
  filename      = data.archive_file.backfill_orchestrator_zip.output_path # Use the zip file created by archive_file
  source_code_hash = data.archive_file.backfill_orchestrator_zip.output_base64sha256 # Use the hash from archive_file

  role    = aws_iam_role.lambda_exec_role.arn
  timeout = 900 # From serverless.yml
  memory_size = 128 # From serverless.yml

  environment {
    variables = {
      SCRAPER_LAMBDA_NAME = aws_lambda_function.tiingo_scraper_lambda.function_name # Reference the scraper function name
      S3_BUCKET_NAME      = data.aws_s3_bucket.tiingo_data_bucket.bucket # Reference the S3 bucket name
    }
  }
}

# EventBridge Rule for daily trigger at 2 AM for scraper
resource "aws_cloudwatch_event_rule" "daily_tiingo_scraper_schedule" {
  name                = "daily-tiingo-scraper-schedule"
  description         = "Triggers the Tiingo price scraper Lambda daily at 2 AM"
  schedule_expression = "cron(0 2 * * ? *)" # 2:00 AM daily UTC

  tags = {
    ManagedBy = "Terraform"
  }
}

# EventBridge Target to invoke the scraper Lambda daily
resource "aws_cloudwatch_event_target" "tiingo_scraper_daily_target" {
  rule      = aws_cloudwatch_event_rule.daily_tiingo_scraper_schedule.name
  target_id = "InvokeTiingoScraperLambdaDaily" # Changed target_id for clarity
  arn       = aws_lambda_function.tiingo_scraper_lambda.arn
  input     = jsonencode({"type": "daily"}) # Pass the 'daily' event type payload
}

# Lambda Permission for EventBridge to invoke the scraper Lambda daily
resource "aws_lambda_permission" "allow_eventbridge_to_invoke_tiingo_scraper_daily" {
  statement_id  = "AllowExecutionFromEventBridgeDaily" # Changed statement_id for clarity
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.tiingo_scraper_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.daily_tiingo_scraper_schedule.arn
}

# EventBridge Rule for hourly trigger for backfill orchestrator
resource "aws_cloudwatch_event_rule" "hourly_backfill_orchestrator_schedule" {
  name                = "hourly-backfill-orchestrator-schedule"
  description         = "Triggers the Tiingo backfill orchestrator Lambda hourly"
  schedule_expression = "cron(0 * * * ? *)" # Hourly at the start of the hour UTC

  tags = {
    ManagedBy = "Terraform"
  }
}

# EventBridge Target to invoke the backfill orchestrator Lambda hourly
resource "aws_cloudwatch_event_target" "backfill_orchestrator_hourly_target" {
  rule      = aws_cloudwatch_event_rule.hourly_backfill_orchestrator_schedule.name
  target_id = "InvokeBackfillOrchestratorLambdaHourly"
  arn       = aws_lambda_function.backfill_orchestrator_lambda.arn
  input     = jsonencode({}) # Empty payload for orchestrator
}

# Lambda Permission for EventBridge to invoke the backfill orchestrator Lambda hourly
resource "aws_lambda_permission" "allow_eventbridge_to_invoke_backfill_orchestrator_hourly" {
  statement_id  = "AllowExecutionFromEventBridgeHourly"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.backfill_orchestrator_lambda.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.hourly_backfill_orchestrator_schedule.arn
}

# Removed API Gateway resources
# Removed CloudWatch Event Rule and Target (previous ones)
# Removed Lambda permissions for API Gateway and CloudWatch Events (previous ones)

# No outputs defined as API Gateway is removed