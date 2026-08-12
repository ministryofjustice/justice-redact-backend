# Justice Redact Backend (Prototype)

This service provides the API and processing layer for the **Justice Redact** project. It facilitates PDF document uploads, AI-assisted detection, finding reviews, and the application of user-defined redactions for final export.

## Features
- **PDF Processing**: Powered by PyMuPDF.
- **AI-Assisted Detection**: Automated identification of sensitive information.
- **Review Workflow**: Review findings and commit redaction decisions.
- **Final Export**: Generation of sanitized, redacted PDFs.

## Tech Stack
- **Framework**: [FastAPI](https://fastapi.tiangolo.com)
- **Language**: Python 3.12+
- **PDF Engine**: [PyMuPDF](https://pymupdf.readthedocs.io)
- **Storage**: Local file system (Prototype stage)

## Database migrations

Alembic owns PostgreSQL schema changes. With the database environment variables
configured, apply all migrations with:

```shell
uv run alembic upgrade head
```

Create a migration after changing the SQLAlchemy models with:

```shell
uv run alembic revision --autogenerate -m "describe the schema change"
```

Always review generated migrations before committing them. The initial revision
creates the three application tables on an empty database and adopts an existing
environment when all three baseline tables are already present. It refuses a
partial baseline rather than guessing how to repair it.

Deployments run migrations in a single Kubernetes Job and wait for it to finish
before updating the backend Deployment. Application replicas do not run
migrations during startup.

## 📂 Project Structure
```text
├── routes/
│   └── documents.py      # API endpoints & logic
└── data/
    ├── uploads/          # Original PDF source files
    ├── processed/        # AI analysis (JSON output)
    ├── decisions/        # User-approved redaction metadata
    └── exports/          # Final redacted PDF documents

## 📖 Deployment Documentation

* [Deployment & Automated Release Guide](.github/workflows/DEPLOYMENT.md) – Overview of our deployment pipelines, environment tagging rules, and release creation process.