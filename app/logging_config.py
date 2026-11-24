"""
Structured (JSON) logging setup for justice-redact-backend.

Why JSON: Fluent Bit ships whatever hits stdout / this log file as-is. If
log lines are plain text, they arrive in OpenSearch as one unsearchable
blob per line. JSON gives every field (event, document_id, status_code,
duration_ms, etc.) its own indexed field, so it can be filtered/aggregated
in OpenSearch dashboards.

Why a file handler as well as stdout: containers in a Kubernetes pod don't
share stdout with each other directly - there's no simple way for the
fluent-bit sidecar container to "see" what the app container prints. So the
app also writes the same structured logs to a file on a shared emptyDir
volume (/var/log/app, mounted by both containers - see deployment.yml),
which Fluent Bit tails.

IMPORTANT - data protection: this module (and any code that uses `logger`)
must never be passed a data subject's name, prison number, or other
identifying detail via the `extra={}` dict. Those fields get indexed into
OpenSearch, a separate data store from the primary RDS/S3 data, with its
own retention and access characteristics. See document_processing_service.py
for the pattern of deliberately omitting subjectName/subjectPrisonNumber
from every log call.
"""

import logging
import sys

from pythonjsonlogger import jsonlogger

# Shared with the fluent-bit sidecar container via the "logs" emptyDir
# volume mounted at this same path in deployment.yml.
LOG_FILE_PATH = "/var/log/app/app.log"


def configure_logging() -> None:
    """
    Configure the root logger with two handlers:
      - stdout: so `kubectl logs` still shows readable output for local
        debugging, same as before this change.
      - file: written to LOG_FILE_PATH, tailed by the fluent-bit sidecar
        and shipped to the OpenSearch domain via the in-cluster proxy.

    Must be called once, as early as possible in app/main.py - before
    `app = FastAPI(...)` and before any router imports that might log at
    import time - so nothing is missed.
    """
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(LOG_FILE_PATH)
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [stdout_handler, file_handler]
    root.setLevel(logging.INFO)


# Shared logger instance imported by main.py and every router/service
# module that emits application events (e.g. redactions.py,
# document_processing_service.py).
logger = logging.getLogger("justice-redact-backend")