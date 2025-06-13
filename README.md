# AWS-AI-Base

This project is a serverless, AWS-based, fully Dockerized data pipeline for collecting and backfilling stock data using Lambda, ECR, and Terraform.

## Project Structure

- `src/tiingo_scraper_lambda/` - Tiingo price scraper Lambda (Docker-based)
- `src/tiingo_scraper/` - Backfill orchestrator Lambda (Docker-based)
- `main.tf` - Terraform configuration for all AWS resources
- `terraform.tfvars` - Image URIs for Lambda Docker deployment
- `variables.tf` - Terraform variable definitions
- `docs/` - Project documentation
- `requests_layer/` - (legacy, not used) requirements for old Lambda layer

## Deployment Workflow

### Prerequisites

- Python 3.12+
- Docker (with buildx support)
- AWS CLI configured with your profile
- Terraform 1.5+

### Build and Push Lambda Images

1. **Build and push the tiingo scraper Lambda image:**
   ```bash
   docker buildx build --platform linux/amd64 --push -t 767398003959.dkr.ecr.us-east-1.amazonaws.com/tiingo-scraper:<tag> src/tiingo_scraper_lambda
   ```

2. **Build and push the backfill orchestrator Lambda image:**
   ```bash
   docker buildx build --platform linux/amd64 --push -t 767398003959.dkr.ecr.us-east-1.amazonaws.com/backfill-orchestrator:<tag> src/tiingo_scraper
   ```

3. **Update `terraform.tfvars` with the new image tags:**
   ```
   tiingo_scraper_image_uri = "767398003959.dkr.ecr.us-east-1.amazonaws.com/tiingo-scraper:<tag>"
   backfill_orchestrator_image_uri = "767398003959.dkr.ecr.us-east-1.amazonaws.com/backfill-orchestrator:<tag>"
   ```

### Deploy with Terraform

```bash
terraform apply -auto-approve
```

This will update the Lambda functions to use the new Docker images.

## Adding New Modules

- Create a new directory under `src/` for your Lambda.
- Write a Dockerfile using the AWS Lambda Python base image.
- Build and push the image to ECR as above.
- Add a new `aws_lambda_function` resource to `main.tf` using `package_type = "Image"` and the ECR image URI.
- Add any required IAM roles, policies, and triggers in Terraform.

## Environment Variables

- All Lambda environment variables are set in Terraform under the `environment` block for each function.
- Secrets (like API keys) should be managed via AWS Secrets Manager or SSM for production.

## Documentation

- See `docs/20_INFRASTRUCTURE.md` and `docs/FOLDER_STRUCTURE.md` for more details on the infrastructure and file layout.

## Notes

- All Lambda deployment is now Docker/ECR-based. No zip packaging or Lambda layers are used.
- The project is ready for modular expansion using Docker and Terraform.
