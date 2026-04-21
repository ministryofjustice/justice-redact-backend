from pathlib import Path

DATA_DIR = Path("data")

UPLOAD_DIR = DATA_DIR / "uploads"
PROCESSED_DIR = DATA_DIR / "processed"
DECISIONS_DIR = DATA_DIR / "decisions"
EXPORTS_DIR = DATA_DIR / "exports"

for path in [UPLOAD_DIR, PROCESSED_DIR, DECISIONS_DIR, EXPORTS_DIR]:
    path.mkdir(parents=True, exist_ok=True)
