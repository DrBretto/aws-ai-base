# 📂 Folder & Naming Bible

<project_root>/
├── README.md
├── docs/
│   ├── FOLDER_STRUCTURE.md        ← this file
│   └── 20_INFRASTRUCTURE.md       ← stack outputs & resource notes
├── src/
│   ├── tiingo_scraper_lambda/     ← Docker-based Lambda: tiingo-price-scraper
│   │   ├── lambda_function.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── tiingo_scraper/            ← Docker-based Lambda: backfill orchestrator
│       ├── backfill_orchestrator.py
│       └── Dockerfile
├── terraform.tfvars               ← ECR image URIs for Lambda deployment
├── variables.tf                   ← Terraform variable definitions
├── main.tf                        ← Terraform configuration
├── .gitignore
├── .terraform.lock.hcl
├── requests_layer/                ← (legacy, not used)
│   └── requirements.txt
└── progress.json                  ← S3 state file for backfill progress

## Conventions

- **Resource names** `${project}-${service}` (kebab‑case).
- **S3 bucket** `${project}-bucket` (kebab‑case, no underscores).
- **Lambda folders** snake_case; handler file `lambda_function.py`, function `lambda_handler`.
- **Dockerfiles** Each Lambda has its own Dockerfile in its folder.
- **Secrets** Use SSM Parameter Store or Secrets Manager—no plain creds in repo.
- **Python style** (Optional) `black` + `ruff` if you enable hooks later.
- **Branch flow** `dev` → `main`; after each checklist box, run `git commit && git push`.

## Notes

- All Lambda deployment is Docker/ECR-based. No zip packaging or Lambda layers are used.
- To add a new Lambda, create a new folder in `src/`, add a Dockerfile, and follow the ECR/Terraform workflow.