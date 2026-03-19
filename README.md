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

## 📂 Project Structure
```text
├── routes/
│   └── documents.py      # API endpoints & logic
└── data/
    ├── uploads/          # Original PDF source files
    ├── processed/        # AI analysis (JSON output)
    ├── decisions/        # User-approved redaction metadata
    └── exports/          # Final redacted PDF documents
