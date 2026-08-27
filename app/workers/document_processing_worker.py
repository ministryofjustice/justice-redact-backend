import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import threading
import signal

from app.logging_config import configure_logging, logger
from app.services.document_processing_service import (
    DocumentProcessingCancelled,
    process_document_pipeline,
)
from app.services.s3_keys import document_prefix
from app.services.s3_service import delete_s3_prefix
from app.services.document_store import (
    fail_document_processing_attempt,
    get_document,
    is_document_processing_owner,
    renew_document_processing_lease,
    try_claim_document_processing,
)
from app.services.sqs_service import (
    delete_document_processing_message,
    extend_document_processing_message_visibility,
    receive_document_processing_messages,
)


@dataclass(frozen=True)
class DocumentProcessingMessage:
    schema_version: int
    job_id: str
    document_id: str


PROCESSING_LEASE_SECONDS = 900
HEARTBEAT_INTERVAL_SECONDS = 300
MAX_RECEIVE_COUNT = 3


def run_processing_heartbeat(
    *,
    stop_event: threading.Event,
    document_id: str,
    job_id: str,
    claim_id: str,
    receipt_handle: str,
) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        lease_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=PROCESSING_LEASE_SECONDS,
        )

        try:
            extend_document_processing_message_visibility(
                receipt_handle=receipt_handle,
                visibility_timeout_seconds=PROCESSING_LEASE_SECONDS,
            )
        except Exception as exc:
            logger.error(
                "document_processing_visibility_extension_failed",
                extra={
                    "event": "document_processing_visibility_extension_failed",
                    "document_id": document_id,
                    "job_id": job_id,
                    "error_type": type(exc).__name__,
                },
            )

        try:
            renewed = renew_document_processing_lease(
                document_id=document_id,
                job_id=job_id,
                claim_id=claim_id,
                lease_expires_at=lease_expires_at,
            )
        except Exception as exc:
            logger.error(
                "document_processing_heartbeat_lease_failed",
                extra={
                    "event": "document_processing_heartbeat_lease_failed",
                    "document_id": document_id,
                    "job_id": job_id,
                    "error_type": type(exc).__name__,
                },
            )
            continue

        if not renewed:
            logger.warning(
                "document_processing_heartbeat_rejected",
                extra={
                    "event": "document_processing_heartbeat_rejected",
                    "document_id": document_id,
                    "job_id": job_id,
                },
            )
            return

        logger.info(
            "document_processing_heartbeat",
            extra={
                "event": "document_processing_heartbeat",
                "document_id": document_id,
                "job_id": job_id,
            },
        )


def process_sqs_message(message: dict) -> None:
    receipt_handle = message.get("ReceiptHandle")
    body = message.get("Body")
    attributes = message.get("Attributes", {})

    if not isinstance(receipt_handle, str) or not receipt_handle:
        raise ValueError("SQS message is missing ReceiptHandle")

    if not isinstance(body, str):
        raise ValueError("SQS message is missing Body")

    parsed = parse_document_processing_message(body)

    receive_count_raw = attributes.get("ApproximateReceiveCount", "1")

    try:
        receive_count = int(receive_count_raw)
    except (TypeError, ValueError):
        receive_count = 1

    document = get_document(parsed.document_id)

    if document is None:
        logger.warning(
            "document_processing_message_discarded",
            extra={
                "event": "document_processing_message_discarded",
                "reason": "document_not_found",
                "document_id": parsed.document_id,
                "job_id": parsed.job_id,
            },
        )

        delete_document_processing_message(
            receipt_handle=receipt_handle,
        )
        return

    if document["processingJobId"] != parsed.job_id:
        logger.warning(
            "document_processing_message_discarded",
            extra={
                "event": "document_processing_message_discarded",
                "reason": "stale_job",
                "document_id": parsed.document_id,
                "job_id": parsed.job_id,
            },
        )

        delete_document_processing_message(
            receipt_handle=receipt_handle,
        )
        return

    if document["status"] == "ready_for_review":
        logger.info(
            "document_processing_message_discarded",
            extra={
                "event": "document_processing_message_discarded",
                "reason": "already_completed",
                "document_id": parsed.document_id,
                "job_id": parsed.job_id,
            },
        )

        delete_document_processing_message(
            receipt_handle=receipt_handle,
        )
        return

    claim_id = str(uuid4())
    lease_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=PROCESSING_LEASE_SECONDS,
    )

    claimed = try_claim_document_processing(
        document_id=parsed.document_id,
        job_id=parsed.job_id,
        claim_id=claim_id,
        attempt_count=receive_count,
        lease_expires_at=lease_expires_at,
    )

    if not claimed:
        logger.info(
            "document_processing_message_not_claimed",
            extra={
                "event": "document_processing_message_not_claimed",
                "document_id": parsed.document_id,
                "job_id": parsed.job_id,
            },
        )
        return

    logger.info(
        "document_processing_started",
        extra={
            "event": "document_processing_started",
            "document_id": parsed.document_id,
            "job_id": parsed.job_id,
            "attempt": receive_count,
        },
    )

    heartbeat_stop_event = threading.Event()

    heartbeat_thread = threading.Thread(
        target=run_processing_heartbeat,
        kwargs={
            "stop_event": heartbeat_stop_event,
            "document_id": parsed.document_id,
            "job_id": parsed.job_id,
            "claim_id": claim_id,
            "receipt_handle": receipt_handle,
        },
        name=f"document-processing-heartbeat-{parsed.document_id}",
        daemon=True,
    )

    heartbeat_thread.start()

    try:
        process_document_pipeline(
            parsed.document_id,
            document["documentType"],
            job_id=parsed.job_id,
            claim_id=claim_id,
            is_processing_active=lambda: is_document_processing_owner(
                document_id=parsed.document_id,
                job_id=parsed.job_id,
                claim_id=claim_id,
            ),
        )

        delete_document_processing_message(
            receipt_handle=receipt_handle,
        )

        logger.info(
            "document_processing_job_completed",
            extra={
                "event": "document_processing_job_completed",
                "document_id": parsed.document_id,
                "job_id": parsed.job_id,
                "attempt": receive_count,
            },
        )

    except DocumentProcessingCancelled:
        try:
            delete_s3_prefix(document_prefix(parsed.document_id))
        except Exception as exc:
            logger.error(
                "document_processing_cancel_cleanup_failed",
                extra={
                    "event": "document_processing_cancel_cleanup_failed",
                    "document_id": parsed.document_id,
                    "job_id": parsed.job_id,
                    "error_type": type(exc).__name__,
                },
            )

        delete_document_processing_message(
            receipt_handle=receipt_handle,
        )

        logger.info(
            "document_processing_cancelled",
            extra={
                "event": "document_processing_cancelled",
                "document_id": parsed.document_id,
                "job_id": parsed.job_id,
            },
        )

        return

    except Exception as exc:
        terminal = receive_count >= MAX_RECEIVE_COUNT

        fail_document_processing_attempt(
            document_id=parsed.document_id,
            job_id=parsed.job_id,
            claim_id=claim_id,
            terminal=terminal,
        )

        logger.error(
            "document_processing_job_failed",
            extra={
                "event": "document_processing_job_failed",
                "document_id": parsed.document_id,
                "job_id": parsed.job_id,
                "attempt": receive_count,
                "terminal": terminal,
                "error_type": type(exc).__name__,
            },
        )

        raise

    finally:
        heartbeat_stop_event.set()
        heartbeat_thread.join(timeout=5)


def parse_document_processing_message(body: str) -> DocumentProcessingMessage:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("SQS message body is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("SQS message body must be a JSON object")

    if payload.get("schemaVersion") != 1:
        raise ValueError("Unsupported SQS message schema version")

    if payload.get("jobType") != "document_processing":
        raise ValueError("Unsupported SQS job type")

    job_id = payload.get("jobId")
    document_id = payload.get("documentId")

    if not isinstance(job_id, str) or not job_id.strip():
        raise ValueError("SQS message is missing jobId")

    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("SQS message is missing documentId")

    return DocumentProcessingMessage(
        schema_version=1,
        job_id=job_id,
        document_id=document_id,
    )


def run_worker() -> None:
    configure_logging()

    shutdown_requested = threading.Event()

    def handle_shutdown(signum, _frame) -> None:
        if shutdown_requested.is_set():
            return

        shutdown_requested.set()

        logger.info(
            "document_processing_worker_shutdown_requested",
            extra={
                "event": "document_processing_worker_shutdown_requested",
                "signal": signal.Signals(signum).name,
            },
        )

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    logger.info(
        "document_processing_worker_started",
        extra={
            "event": "document_processing_worker_started",
        },
    )

    while not shutdown_requested.is_set():
        try:
            messages = receive_document_processing_messages()
        except Exception as exc:
            logger.error(
                "document_processing_worker_poll_failed",
                extra={
                    "event": "document_processing_worker_poll_failed",
                    "error_type": type(exc).__name__,
                },
            )
            continue

        # SIGTERM may have arrived while SQS long polling was in progress.
        # Do not begin processing a newly received document after shutdown.
        if shutdown_requested.is_set():
            for message in messages:
                receipt_handle = message.get("ReceiptHandle")

                if not receipt_handle:
                    continue

                try:
                    extend_document_processing_message_visibility(
                        receipt_handle=receipt_handle,
                        visibility_timeout_seconds=0,
                    )
                except Exception as exc:
                    logger.error(
                        "document_processing_worker_message_release_failed",
                        extra={
                            "event": (
                                "document_processing_worker_message_release_failed"
                            ),
                            "error_type": type(exc).__name__,
                        },
                    )

            break

        for message in messages:
            try:
                process_sqs_message(message)
            except Exception as exc:
                logger.error(
                    "document_processing_worker_message_failed",
                    extra={
                        "event": "document_processing_worker_message_failed",
                        "error_type": type(exc).__name__,
                    },
                )

            if shutdown_requested.is_set():
                break

    logger.info(
        "document_processing_worker_stopped",
        extra={
            "event": "document_processing_worker_stopped",
        },
    )


if __name__ == "__main__":
    run_worker()
