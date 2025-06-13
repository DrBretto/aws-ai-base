# AI.md — Project Reference for Future AI Agents

## Project Overview

This project is a serverless AWS data pipeline for collecting, backfilling, and processing stock data. It is fully Dockerized, with all Lambda functions deployed as container images via ECR and managed by Terraform.

## Key Components

- **Lambdas (Docker/ECR):**
  - `tiingo-price-scraper`: Fetches daily stock data from Tiingo and saves to S3.
  - `tiingo-backfill-orchestrator`: Orchestrates historical backfill in 6-month chunks, triggers the scraper Lambda, and updates progress in S3.

- **Infrastructure as Code:** All AWS resources are managed in `main.tf` (Terraform).
- **ECR:** Each Lambda has its own ECR repository. Images must be built for `linux/amd64` and pushed with a unique tag for each deployment.
- **S3:** All data is stored in `aws-ai-base-bucket`.
- **IAM:** Roles and policies are defined in Terraform. Lambdas use a shared execution role with policies for S3, logging, and Lambda invocation.
- **EventBridge:** Schedules daily and hourly Lambda invocations.

## Deployment Workflow

1. **Build Docker Images:**
   - Use `docker buildx build --platform linux/amd64 --push -t <ECR_URI>:<tag> <lambda_dir>`
   - Tag must be unique for each deployment (e.g., timestamp or commit hash).

2. **Update Terraform Variables:**
   - Set `tiingo_scraper_image_uri` and `backfill_orchestrator_image_uri` in `terraform.tfvars` to the new ECR image URIs.

3. **Deploy:**
   - Run `terraform apply -auto-approve` to update Lambda functions.

4. **Invoke/Test:**
   - Use `aws lambda invoke` to test functions.
   - Check logs with `aws logs get-log-events`.

## Adding New Modules

- Create a new folder in `src/` for the Lambda.
- Add a Dockerfile using the AWS Lambda Python base image.
- Build and push the image to a new ECR repo.
- Add a new `aws_lambda_function` resource in Terraform with `package_type = "Image"` and the ECR image URI.
- Add any required IAM, S3, or EventBridge resources in Terraform.
- Update documentation as needed.

## Environment Variables

- All Lambda environment variables are set in Terraform.
- Secrets should be managed via AWS Secrets Manager or SSM for production.

## Naming & Structure

- All resource names are kebab-case.
- Lambda handler files are `lambda_function.py` (scraper) and `backfill_orchestrator.py` (orchestrator).
- Dockerfiles are in each Lambda's folder.
- No Lambda layers or zip packaging are used.

## Troubleshooting

- If Lambda does not update, ensure the ECR image tag is unique and update `terraform.tfvars`.
- If you see `Runtime.InvalidEntrypoint` or `exec format error`, the image is not built for `linux/amd64`. Use `docker buildx build --platform linux/amd64 --push ...`.
- Always check CloudWatch logs for runtime errors.

## Project Conventions

- All infrastructure is managed as code.
- All Lambdas are Docker/ECR-based.
- No legacy SAM, zip, or layer artifacts remain.
- To add new features, follow the Docker/ECR/Terraform workflow.

## Contact

- For any future AI agent: Use this file as your primary reference for project structure, deployment, and conventions. Always check for the latest ECR image tags and update Terraform accordingly.