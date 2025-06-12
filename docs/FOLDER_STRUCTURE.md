# 📂 Folder & Naming Bible

<project_root>/
├── README.md
├── docs/
│   ├── FOLDER_STRUCTURE.md        ← this file
│   └── 20_INFRASTRUCTURE.md       ← stack outputs & resource notes
├── infra/
│   └── sam/                       ← template.yaml, .samconfig.toml
├── src/
│   └── hello_world/               ← sample Lambda
│       └── app.py
├── config/
│   └── SECRETS_TEMPLATE.env       ← **never commit real keys**
└── .gitignore

## Conventions
- **Resource names** `${project}-${stage}-${service}` (kebab‑case).
- **S3 bucket** `${project}-bucket` (kebab‑case, no underscores).
- **Lambda folders** snake_case; handler file `app.py`, function `lambda_handler`.
- **Secrets** Use SSM Parameter Store—no plain creds in repo.
- **Python style** (Optional) `black` + `ruff` if you enable hooks later.
- **Branch flow** `dev` → `main`; after each checklist box, run `git commit && git push`.