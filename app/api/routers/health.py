from fastapi import APIRouter

from app.core.paths import UPLOAD_DIR

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {
        "status": "ok",
        "uploadDirExists": UPLOAD_DIR.exists(),
    }
