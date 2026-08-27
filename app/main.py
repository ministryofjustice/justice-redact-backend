import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.logging_config import configure_logging, logger
from app.api.routers.documents import router as documents_router
from app.api.routers.exports import router as exports_router
from app.api.routers.redactions import router as redactions_router
from app.api.routers.review import router as review_router
from app.api.routers.health import router as health_router

# Must run before anything else logs, so both the app and uvicorn emit
# structured JSON to stdout + the shared file the Fluent Bit sidecar tails
# (see app/logging_config.py for why both destinations are needed).
configure_logging()

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


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Logs a single structured event per HTTP request/response, covering the
    "all requests" half of the "log all events" requirement (the other
    half - application-level events like redactions - is logged directly
    inside the relevant router/service modules instead, since this
    middleware has no visibility into what a route actually does).
    """
    # Skip liveness-probe traffic. The probe hits this every 20s per
    # deployment.yml's livenessProbe config, which would otherwise be
    # ~4,300 log lines/day of pure noise in OpenSearch with no useful
    # information (always the same path, always a 200).
    if request.url.path == "/health":
        return await call_next(request)

    request_id = str(uuid.uuid4())
    start = time.time()

    response = await call_next(request)

    logger.info(
        "http_request",
        extra={
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((time.time() - start) * 1000, 2),
            "client_ip": request.client.host if request.client else None,
        },
    )
    # Echoed back to the client too, so it can be correlated with the
    # OpenSearch log entry from the frontend / support tickets if needed.
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(health_router)
app.include_router(documents_router)
app.include_router(review_router)
app.include_router(redactions_router)
app.include_router(exports_router)