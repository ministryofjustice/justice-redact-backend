from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routers.documents import router as documents_router
from app.api.routers.exports import router as exports_router
from app.api.routers.redactions import router as redactions_router
from app.api.routers.review import router as review_router
from app.api.routers.health import router as health_router


app = FastAPI(title="Justice Redact Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(documents_router)
app.include_router(review_router)
app.include_router(redactions_router)
app.include_router(exports_router)
