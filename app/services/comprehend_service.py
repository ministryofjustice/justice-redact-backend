import os
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

# Read from the env var injected by deployment.yml
AP_COMPREHEND_ROLE_ARN = os.environ.get("AP_COMPREHEND_ROLE_ARN")

# Comprehend has a 5,000 UTF-8 byte limit per request for synchronous calls
COMPREHEND_BYTE_LIMIT = 5000


def _get_comprehend_client():
    """
    Assumes the cross-account role in the Analytical Platform AWS account
    and returns a Comprehend client using the temporary credentials.

    The pod's IRSA credentials (bound to its Kubernetes service account)
    are picked up automatically by boto3 — no access keys needed.
    """
    if not AP_COMPREHEND_ROLE_ARN:
        raise HTTPException(
            status_code=500,
            detail="AP_COMPREHEND_ROLE_ARN is not configured",
        )

    try:
        sts = boto3.client("sts", region_name="eu-west-2")
        assumed = sts.assume_role(
            RoleArn=AP_COMPREHEND_ROLE_ARN,
            RoleSessionName="justice-redact-comprehend",
            DurationSeconds=3600,
        )
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to assume Analytical Platform role: {exc}",
        )

    creds = assumed["Credentials"]
    return boto3.client(
        "comprehend",
        region_name="eu-west-2",
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )


def _truncate_to_byte_limit(text: str, limit: int = COMPREHEND_BYTE_LIMIT) -> str:
    """
    Comprehend's synchronous API accepts a maximum of 5,000 UTF-8 bytes.
    Truncates the text to stay within that limit.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    return encoded[:limit].decode("utf-8", errors="ignore")


def detect_pii_entities(text: str, language_code: str = "en") -> dict:
    """
    Calls AWS Comprehend DetectPiiEntities on the provided text.

    Returns a dict of detected PII entities, e.g.:
    {
        "Entities": [
            {"Score": 0.99, "Type": "NAME", "BeginOffset": 0, "EndOffset": 10},
            ...
        ]
    }
    """
    client = _get_comprehend_client()
    safe_text = _truncate_to_byte_limit(text)

    try:
        response = client.detect_pii_entities(Text=safe_text, LanguageCode=language_code)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Comprehend DetectPiiEntities failed: {exc}",
        )

    return response


def detect_entities(text: str, language_code: str = "en") -> dict:
    """
    Calls AWS Comprehend DetectEntities on the provided text.

    Returns a dict of detected entities (PERSON, LOCATION, ORGANIZATION etc.), e.g.:
    {
        "Entities": [
            {"Score": 0.98, "Type": "PERSON", "Text": "John Smith", "BeginOffset": 0, "EndOffset": 10},
            ...
        ]
    }
    """
    client = _get_comprehend_client()
    safe_text = _truncate_to_byte_limit(text)

    try:
        response = client.detect_entities(Text=safe_text, LanguageCode=language_code)
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Comprehend DetectEntities failed: {exc}",
        )

    return response
