# 20 INFRASTRUCTURE

## Overview

This project is deployed using Terraform and AWS Lambda with Docker images stored in ECR. All Lambda functions are built as Docker images and pushed to ECR, then referenced in Terraform for deployment.

## Key AWS Resources

- **Lambda Functions (Docker/ECR):**
  - `tiingo-price-scraper`: Fetches and saves daily stock data to S3.
  - `tiingo-backfill-orchestrator`: Orchestrates historical backfill in 6-month chunks.

- **ECR Repositories:**
  - `tiingo-scraper`: Stores the Docker image for the tiingo scraper Lambda.
  - `backfill-orchestrator`: Stores the Docker image for the orchestrator Lambda.

- **S3 Bucket:**
  - `aws-ai-base-bucket`: Stores all scraped and backfilled data.

- **IAM Roles and Policies:**
  - `aws-ai-base-lambda-exec-role`: Execution role for all Lambdas.
  - `aws-ai-base-lambda-logging-policy`: Allows Lambdas to write logs to CloudWatch.
  - `aws-ai-base-s3-access-policy`: Allows Lambdas to read/write/delete objects in the S3 bucket.
  - `aws-ai-base-lambda-invoke-policy`: Allows orchestrator to invoke the scraper Lambda.

- **EventBridge (CloudWatch Events):**
  - Triggers the scraper Lambda daily at 2 AM UTC.
  - Triggers the orchestrator Lambda hourly.

## Deployment Workflow

1. Build Docker images for each Lambda using `docker buildx` for `linux/amd64`.
2. Push images to ECR.
3. Update `terraform.tfvars` with the new image URIs.
4. Run `terraform apply` to deploy or update the Lambdas.

## Adding New Modules

- Create a new ECR repo for each new Lambda.
- Build and push the Docker image.
- Add a new `aws_lambda_function` resource in Terraform with `package_type = "Image"` and the ECR image URI.
- Add any required IAM, S3, or EventBridge resources in Terraform.

## Notes

- No Lambda layers or zip packaging are used.
- All environment variables are managed in Terraform.
- All infrastructure is managed as code in `main.tf` and related files.