import json

import boto3

from app.core.settings import settings


sqs_client = boto3.client(
    "sqs",
    region_name=settings.s3_region,
)


def send_document_processing_message(
    *,
    document_id: str,
    job_id: str,
) -> str:
    response = sqs_client.send_message(
        QueueUrl=settings.sqs_queue_url,
        MessageBody=json.dumps(
            {
                "schemaVersion": 1,
                "jobType": "document_processing",
                "jobId": job_id,
                "documentId": document_id,
            }
        ),
    )

    return response["MessageId"]


def receive_document_processing_messages() -> list[dict]:
    response = sqs_client.receive_message(
        QueueUrl=settings.sqs_queue_url,
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
        MessageSystemAttributeNames=["ApproximateReceiveCount"],
    )

    return response.get("Messages", [])


def delete_document_processing_message(
    *,
    receipt_handle: str,
) -> None:
    sqs_client.delete_message(
        QueueUrl=settings.sqs_queue_url,
        ReceiptHandle=receipt_handle,
    )


def extend_document_processing_message_visibility(
    *,
    receipt_handle: str,
    visibility_timeout_seconds: int,
) -> None:
    sqs_client.change_message_visibility(
        QueueUrl=settings.sqs_queue_url,
        ReceiptHandle=receipt_handle,
        VisibilityTimeout=visibility_timeout_seconds,
    )


def _get_redaction_queue_url() -> str:
    queue_url = settings.redaction_sqs_queue_url

    if not queue_url:
        raise RuntimeError("REDACTION_SQS_QUEUE_URL is not configured")

    return queue_url


def send_redaction_processing_message(
    *,
    document_id: str,
    run_id: str,
) -> str:
    response = sqs_client.send_message(
        QueueUrl=_get_redaction_queue_url(),
        MessageBody=json.dumps(
            {
                "schemaVersion": 1,
                "jobType": "redaction_processing",
                "runId": run_id,
                "documentId": document_id,
            }
        ),
    )

    return response["MessageId"]


def receive_redaction_processing_messages() -> list[dict]:
    response = sqs_client.receive_message(
        QueueUrl=_get_redaction_queue_url(),
        MaxNumberOfMessages=1,
        WaitTimeSeconds=20,
        MessageSystemAttributeNames=["ApproximateReceiveCount"],
    )

    return response.get("Messages", [])


def delete_redaction_processing_message(
    *,
    receipt_handle: str,
) -> None:
    sqs_client.delete_message(
        QueueUrl=_get_redaction_queue_url(),
        ReceiptHandle=receipt_handle,
    )


def extend_redaction_processing_message_visibility(
    *,
    receipt_handle: str,
    visibility_timeout_seconds: int,
) -> None:
    sqs_client.change_message_visibility(
        QueueUrl=_get_redaction_queue_url(),
        ReceiptHandle=receipt_handle,
        VisibilityTimeout=visibility_timeout_seconds,
    )
