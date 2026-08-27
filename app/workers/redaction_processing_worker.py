import json
import signal
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.logging_config import configure_logging, logger
from app.models.redaction_models import ApplyRedactionsRequest
from app.services.redaction_run_store import (
    claim_redaction_run,
    complete_redaction_run,
    fail_redaction_run,
    get_redaction_run,
    is_redaction_run_owner,
    renew_redaction_run_lease,
)
from app.services.redaction_service import (
    RedactionProcessingCancelled,
    apply_redactions_for_document,
)
from app.services.s3_keys import redaction_run_prefix
from app.services.s3_service import delete_s3_prefix
from app.services.sqs_service import (
    delete_redaction_processing_message,
    extend_redaction_processing_message_visibility,
    receive_redaction_processing_messages,
)


@dataclass(frozen=True)
class RedactionProcessingMessage:
    schema_version: int
    run_id: str
    document_id: str


PROCESSING_LEASE_SECONDS = 900
HEARTBEAT_INTERVAL_SECONDS = 300
MAX_RECEIVE_COUNT = 3


def run_processing_heartbeat(
    *,
    stop_event: threading.Event,
    document_id: str,
    run_id: str,
    claim_id: str,
    receipt_handle: str,
) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        lease_expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=PROCESSING_LEASE_SECONDS,
        )

        try:
            extend_redaction_processing_message_visibility(
                receipt_handle=receipt_handle,
                visibility_timeout_seconds=PROCESSING_LEASE_SECONDS,
            )
        except Exception as exc:
            logger.error(
                "redaction_processing_visibility_extension_failed",
                extra={
                    "event": "redaction_processing_visibility_extension_failed",
                    "document_id": document_id,
                    "run_id": run_id,
                    "error_type": type(exc).__name__,
                },
            )

        try:
            renewed = renew_redaction_run_lease(
                run_id=run_id,
                claim_id=claim_id,
                lease_expires_at=lease_expires_at,
            )
        except Exception as exc:
            logger.error(
                "redaction_processing_heartbeat_lease_failed",
                extra={
                    "event": "redaction_processing_heartbeat_lease_failed",
                    "document_id": document_id,
                    "run_id": run_id,
                    "error_type": type(exc).__name__,
                },
            )
            continue

        if not renewed:
            logger.warning(
                "redaction_processing_heartbeat_rejected",
                extra={
                    "event": "redaction_processing_heartbeat_rejected",
                    "document_id": document_id,
                    "run_id": run_id,
                },
            )
            return

        logger.info(
            "redaction_processing_heartbeat",
            extra={
                "event": "redaction_processing_heartbeat",
                "document_id": document_id,
                "run_id": run_id,
            },
        )


def parse_redaction_processing_message(
    body: str,
) -> RedactionProcessingMessage:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError("SQS message body is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("SQS message body must be a JSON object")

    if payload.get("schemaVersion") != 1:
        raise ValueError("Unsupported SQS message schema version")

    if payload.get("jobType") != "redaction_processing":
        raise ValueError("Unsupported SQS job type")

    run_id = payload.get("runId")
    document_id = payload.get("documentId")

    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("SQS message is missing runId")

    if not isinstance(document_id, str) or not document_id.strip():
        raise ValueError("SQS message is missing documentId")

    return RedactionProcessingMessage(
        schema_version=1,
        run_id=run_id,
        document_id=document_id,
    )


def process_sqs_message(message: dict) -> None:
    receipt_handle = message.get("ReceiptHandle")
    body = message.get("Body")
    attributes = message.get("Attributes", {})

    if not isinstance(receipt_handle, str) or not receipt_handle:
        raise ValueError("SQS message is missing ReceiptHandle")

    if not isinstance(body, str):
        raise ValueError("SQS message is missing Body")

    parsed = parse_redaction_processing_message(body)

    receive_count_raw = attributes.get(
        "ApproximateReceiveCount",
        "1",
    )

    try:
        receive_count = int(receive_count_raw)
    except (TypeError, ValueError):
        receive_count = 1

    redaction_run = get_redaction_run(parsed.run_id)

    if redaction_run is None:
        logger.warning(
            "redaction_processing_message_discarded",
            extra={
                "event": "redaction_processing_message_discarded",
                "reason": "run_not_found",
                "document_id": parsed.document_id,
                "run_id": parsed.run_id,
            },
        )

        delete_redaction_processing_message(
            receipt_handle=receipt_handle,
        )
        return

    if redaction_run["documentId"] != parsed.document_id:
        logger.warning(
            "redaction_processing_message_discarded",
            extra={
                "event": "redaction_processing_message_discarded",
                "reason": "document_mismatch",
                "document_id": parsed.document_id,
                "run_id": parsed.run_id,
            },
        )

        delete_redaction_processing_message(
            receipt_handle=receipt_handle,
        )
        return

    if redaction_run["status"] in {
        "completed",
        "cancelled",
    }:
        logger.info(
            "redaction_processing_message_discarded",
            extra={
                "event": "redaction_processing_message_discarded",
                "reason": redaction_run["status"],
                "document_id": parsed.document_id,
                "run_id": parsed.run_id,
            },
        )

        delete_redaction_processing_message(
            receipt_handle=receipt_handle,
        )
        return

    claim_id = str(uuid4())
    lease_expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=PROCESSING_LEASE_SECONDS,
    )

    claimed = claim_redaction_run(
        run_id=parsed.run_id,
        claim_id=claim_id,
        attempt_count=receive_count,
        lease_expires_at=lease_expires_at,
    )

    if not claimed:
        latest_run = get_redaction_run(parsed.run_id)

        if latest_run is not None and latest_run["status"] in {
            "completed",
            "cancelled",
        }:
            delete_redaction_processing_message(
                receipt_handle=receipt_handle,
            )

        logger.info(
            "redaction_processing_message_not_claimed",
            extra={
                "event": "redaction_processing_message_not_claimed",
                "document_id": parsed.document_id,
                "run_id": parsed.run_id,
            },
        )
        return

    logger.info(
        "redaction_processing_started",
        extra={
            "event": "redaction_processing_started",
            "document_id": parsed.document_id,
            "run_id": parsed.run_id,
            "attempt": receive_count,
        },
    )

    heartbeat_stop_event = threading.Event()

    heartbeat_thread = threading.Thread(
        target=run_processing_heartbeat,
        kwargs={
            "stop_event": heartbeat_stop_event,
            "document_id": parsed.document_id,
            "run_id": parsed.run_id,
            "claim_id": claim_id,
            "receipt_handle": receipt_handle,
        },
        name=("redaction-processing-heartbeat-" f"{parsed.document_id}"),
        daemon=True,
    )

    heartbeat_thread.start()

    try:
        claimed_run = get_redaction_run(parsed.run_id)

        if claimed_run is None:
            raise RedactionProcessingCancelled("Redaction run disappeared after claim")

        snapshot = claimed_run["decisionsSnapshot"]

        if not isinstance(snapshot, dict):
            raise ValueError("Redaction run decisions snapshot is invalid")

        if snapshot.get("documentId") != parsed.document_id:
            raise ValueError("Redaction run snapshot document does not match")

        request = ApplyRedactionsRequest.model_validate(
            {
                **snapshot,
                "expectedRevision": claimed_run["reviewRevision"],
            }
        )

        result = apply_redactions_for_document(
            document_id=parsed.document_id,
            run_id=parsed.run_id,
            request=request,
            is_redaction_active=lambda: (
                is_redaction_run_owner(
                    run_id=parsed.run_id,
                    claim_id=claim_id,
                )
            ),
        )

        completed = complete_redaction_run(
            run_id=parsed.run_id,
            claim_id=claim_id,
            page_counts=result["pageCounts"],
        )

        if not completed:
            raise RedactionProcessingCancelled(
                "Redaction processing lost ownership " "before completion"
            )

        delete_redaction_processing_message(
            receipt_handle=receipt_handle,
        )

        logger.info(
            "redaction_processing_completed",
            extra={
                "event": "redaction_processing_completed",
                "document_id": parsed.document_id,
                "run_id": parsed.run_id,
                "attempt": receive_count,
            },
        )

    except RedactionProcessingCancelled:
        try:
            delete_s3_prefix(
                redaction_run_prefix(
                    parsed.document_id,
                    parsed.run_id,
                )
            )
        except Exception as exc:
            logger.error(
                "redaction_processing_cancel_cleanup_failed",
                extra={
                    "event": ("redaction_processing_cancel_cleanup_failed"),
                    "document_id": parsed.document_id,
                    "run_id": parsed.run_id,
                    "error_type": type(exc).__name__,
                },
            )

        delete_redaction_processing_message(
            receipt_handle=receipt_handle,
        )

        logger.info(
            "redaction_processing_cancelled",
            extra={
                "event": "redaction_processing_cancelled",
                "document_id": parsed.document_id,
                "run_id": parsed.run_id,
            },
        )

        return

    except Exception as exc:
        terminal = receive_count >= MAX_RECEIVE_COUNT

        failed = fail_redaction_run(
            run_id=parsed.run_id,
            claim_id=claim_id,
            error_message="Redaction processing failed",
            terminal=terminal,
        )

        if not failed:
            try:
                delete_s3_prefix(
                    redaction_run_prefix(
                        parsed.document_id,
                        parsed.run_id,
                    )
                )
            except Exception as cleanup_exc:
                logger.error(
                    "redaction_processing_stale_cleanup_failed",
                    extra={
                        "event": ("redaction_processing_stale_cleanup_failed"),
                        "document_id": parsed.document_id,
                        "run_id": parsed.run_id,
                        "error_type": type(cleanup_exc).__name__,
                    },
                )

            delete_redaction_processing_message(
                receipt_handle=receipt_handle,
            )

            logger.info(
                "redaction_processing_failure_discarded",
                extra={
                    "event": ("redaction_processing_failure_discarded"),
                    "document_id": parsed.document_id,
                    "run_id": parsed.run_id,
                    "reason": "lost_authority",
                },
            )

            return

        logger.error(
            "redaction_processing_failed",
            extra={
                "event": "redaction_processing_failed",
                "document_id": parsed.document_id,
                "run_id": parsed.run_id,
                "attempt": receive_count,
                "terminal": terminal,
                "error_type": type(exc).__name__,
            },
        )

        raise

    finally:
        heartbeat_stop_event.set()
        heartbeat_thread.join(timeout=5)


def run_worker() -> None:
    configure_logging()

    shutdown_requested = threading.Event()

    def handle_shutdown(signum, _frame) -> None:
        if shutdown_requested.is_set():
            return

        shutdown_requested.set()

        logger.info(
            "redaction_processing_worker_shutdown_requested",
            extra={
                "event": ("redaction_processing_worker_shutdown_requested"),
                "signal": signal.Signals(signum).name,
            },
        )

    signal.signal(
        signal.SIGTERM,
        handle_shutdown,
    )
    signal.signal(
        signal.SIGINT,
        handle_shutdown,
    )

    logger.info(
        "redaction_processing_worker_started",
        extra={
            "event": "redaction_processing_worker_started",
        },
    )

    while not shutdown_requested.is_set():
        try:
            messages = receive_redaction_processing_messages()
        except Exception as exc:
            logger.error(
                "redaction_processing_worker_poll_failed",
                extra={
                    "event": ("redaction_processing_worker_poll_failed"),
                    "error_type": type(exc).__name__,
                },
            )
            continue

        if shutdown_requested.is_set():
            for message in messages:
                receipt_handle = message.get("ReceiptHandle")

                if not receipt_handle:
                    continue

                try:
                    extend_redaction_processing_message_visibility(
                        receipt_handle=receipt_handle,
                        visibility_timeout_seconds=0,
                    )
                except Exception as exc:
                    logger.error(
                        "redaction_processing_worker_message_release_failed",
                        extra={
                            "event": (
                                "redaction_processing_worker_" "message_release_failed"
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
                    "redaction_processing_worker_message_failed",
                    extra={
                        "event": ("redaction_processing_worker_message_failed"),
                        "error_type": type(exc).__name__,
                    },
                )

            if shutdown_requested.is_set():
                break

    logger.info(
        "redaction_processing_worker_stopped",
        extra={
            "event": "redaction_processing_worker_stopped",
        },
    )


if __name__ == "__main__":
    run_worker()
