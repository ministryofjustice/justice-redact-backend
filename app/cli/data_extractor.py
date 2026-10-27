from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

import boto3
import psycopg
from botocore.credentials import RefreshableCredentials
from botocore.exceptions import ClientError
from botocore.session import get_session
from psycopg.rows import dict_row


EXPORT_PREFIX = "justice-redact-rds"
LOOKBACK_DAYS = 30


CANDIDATE_DOCUMENTS_QUERY = """
    SELECT DISTINCT d.document_id
    FROM documents AS d
    LEFT JOIN redaction_decisions AS rd
        ON rd.document_id = d.document_id
    LEFT JOIN redaction_runs AS rr
        ON rr.document_id = d.document_id
    WHERE
        d.processing_completed_at IS NOT NULL
        AND (
            d.processing_completed_at >= %(cutoff)s
            OR d.updated_at >= %(cutoff)s
            OR d.redaction_started_at >= %(cutoff)s
            OR d.redaction_completed_at >= %(cutoff)s
            OR rd.updated_at >= %(cutoff)s
            OR rr.created_at >= %(cutoff)s
            OR rr.started_at >= %(cutoff)s
            OR rr.completed_at >= %(cutoff)s
            OR rr.cancelled_at >= %(cutoff)s
        )
    ORDER BY d.document_id;
"""


DOCUMENT_QUERY = """
    SELECT
        document_id,
        status,
        document_type,
        subject_name,
        subject_prison_number,
        other_phrases,
        current_redaction_run_id,
        created_at,
        updated_at,
        processing_started_at,
        processing_completed_at,
        redaction_started_at,
        redaction_completed_at
    FROM documents
    WHERE document_id = %(document_id)s;
"""


REVIEW_RESULT_QUERY = """
    SELECT
        document_id,
        review_json
    FROM review_results
    WHERE document_id = %(document_id)s;
"""


REDACTION_DECISION_QUERY = """
    SELECT
        document_id,
        decisions_json,
        revision,
        updated_at
    FROM redaction_decisions
    WHERE document_id = %(document_id)s;
"""


REDACTION_RUN_QUERY = """
    SELECT
        run_id,
        document_id,
        review_revision,
        status,
        processing_progress,
        decisions_snapshot,
        attempt_count,
        page_counts,
        created_at,
        started_at,
        completed_at,
        cancelled_at
    FROM redaction_runs
    WHERE document_id = %(document_id)s
    ORDER BY created_at, run_id;
"""


TABLE_QUERIES = {
    "documents": DOCUMENT_QUERY,
    "review_results": REVIEW_RESULT_QUERY,
    "redaction_decisions": REDACTION_DECISION_QUERY,
    "redaction_runs": REDACTION_RUN_QUERY,
}


def get_required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise ValueError(f"Required environment variable '{name}' is missing.")

    return value


def assume_role_metadata(
    sts_client,
    role_arn: str,
) -> dict[str, str]:
    assumed_role = sts_client.assume_role(
        RoleArn=role_arn,
        RoleSessionName="justice-redact-data-extractor",
    )

    credentials = assumed_role["Credentials"]

    return {
        "access_key": credentials["AccessKeyId"],
        "secret_key": credentials["SecretAccessKey"],
        "token": credentials["SessionToken"],
        "expiry_time": credentials["Expiration"].isoformat(),
    }


def build_s3_client(
    *,
    role_arn: str,
    region: str,
):
    print(
        f"Assuming Analytical Platform S3 role: {role_arn}",
        flush=True,
    )

    sts_client = boto3.client(
        "sts",
        region_name=region,
    )

    def refresh_credentials() -> dict[str, str]:
        return assume_role_metadata(
            sts_client=sts_client,
            role_arn=role_arn,
        )

    refreshable_credentials = RefreshableCredentials.create_from_metadata(
        metadata=refresh_credentials(),
        refresh_using=refresh_credentials,
        method="sts-assume-role",
    )

    botocore_session = get_session()
    botocore_session._credentials = refreshable_credentials
    botocore_session.set_config_variable(
        "region",
        region,
    )

    return boto3.Session(
        botocore_session=botocore_session,
    ).client(
        "s3",
        region_name=region,
    )


def parse_s3_destination(
    destination: str,
) -> tuple[str, str]:
    if not destination.startswith("s3://"):
        raise ValueError("S3_DESTINATION must start with s3://")

    path_without_scheme = destination[5:]
    bucket, _, existing_prefix = path_without_scheme.partition("/")

    if not bucket:
        raise ValueError("S3_DESTINATION must contain a bucket name")

    existing_prefix = existing_prefix.strip("/")

    if existing_prefix:
        export_prefix = f"{existing_prefix}/{EXPORT_PREFIX}"
    else:
        export_prefix = EXPORT_PREFIX

    return bucket, export_prefix


def json_default(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, UUID):
        return str(value)

    if isinstance(value, bytes):
        return value.hex()

    raise TypeError(
        f"Object of type {type(value).__name__} " "is not JSON serializable"
    )


def serialise_row(row: dict) -> bytes:
    return json.dumps(
        row,
        default=json_default,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def object_exists(
    s3_client,
    *,
    bucket: str,
    key: str,
) -> bool:
    try:
        s3_client.head_object(
            Bucket=bucket,
            Key=key,
        )
        return True

    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code")

        status_code = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")

        if (
            error_code
            in {
                "404",
                "NoSuchKey",
                "NotFound",
            }
            or status_code == 404
        ):
            return False

        raise


def row_filename(
    *,
    table_name: str,
    row: dict,
    digest: str,
) -> str:
    if table_name == "redaction_runs":
        return f"{row['run_id']}-{digest}.json"

    if table_name == "redaction_decisions":
        return f"revision-{row['revision']}-" f"{digest}.json"

    return f"snapshot-{digest}.json"


def fetch_candidate_document_ids(
    connection,
    *,
    cutoff: datetime,
) -> list[str]:
    with connection.cursor() as cursor:
        cursor.execute(
            CANDIDATE_DOCUMENTS_QUERY,
            {
                "cutoff": cutoff,
            },
        )

        return [row["document_id"] for row in cursor.fetchall()]


def fetch_document_rows(
    connection,
    *,
    document_id: str,
) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}

    for table_name, query in TABLE_QUERIES.items():
        with connection.cursor() as cursor:
            cursor.execute(
                query,
                {
                    "document_id": document_id,
                },
            )

            result[table_name] = cursor.fetchall()

    return result


def upload_row_if_new(
    s3_client,
    *,
    bucket: str,
    export_prefix: str,
    document_id: str,
    table_name: str,
    row: dict,
) -> bool:
    content = serialise_row(row)
    digest = content_hash(content)

    filename = row_filename(
        table_name=table_name,
        row=row,
        digest=digest,
    )

    key = f"{export_prefix}/" f"{document_id}/" f"{table_name}/" f"{filename}"

    if object_exists(
        s3_client,
        bucket=bucket,
        key=key,
    ):
        print(
            f"SKIP existing: s3://{bucket}/{key}",
            flush=True,
        )
        return False

    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType="application/json",
    )

    print(
        f"UPLOAD: s3://{bucket}/{key}",
        flush=True,
    )

    return True


def main() -> None:
    pghost = get_required_env("PGHOST")
    pgdatabase = get_required_env("PGDATABASE")
    pguser = get_required_env("PGUSER")
    pgpassword = get_required_env("PGPASSWORD")

    destination = get_required_env("S3_DESTINATION")
    role_arn = get_required_env("AP_S3_ROLE_ARN")

    region = os.getenv(
        "AWS_DEFAULT_REGION",
        "eu-west-2",
    )

    bucket, export_prefix = parse_s3_destination(destination)

    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)

    print(
        ("Starting Justice Redact evaluation " f"export. cutoff={cutoff.isoformat()}"),
        flush=True,
    )

    print(
        ("Destination: " f"s3://{bucket}/{export_prefix}/"),
        flush=True,
    )

    s3_client = build_s3_client(
        role_arn=role_arn,
        region=region,
    )

    uploaded_count = 0
    skipped_count = 0

    with psycopg.connect(
        host=pghost,
        dbname=pgdatabase,
        user=pguser,
        password=pgpassword,
        port=5432,
        row_factory=dict_row,
    ) as connection:
        document_ids = fetch_candidate_document_ids(
            connection,
            cutoff=cutoff,
        )

        print(
            (
                f"Found {len(document_ids)} "
                "documents with relevant activity "
                f"in the previous {LOOKBACK_DAYS} days."
            ),
            flush=True,
        )

        for document_id in document_ids:
            print(
                f"Processing document: {document_id}",
                flush=True,
            )

            rows_by_table = fetch_document_rows(
                connection,
                document_id=document_id,
            )

            for (
                table_name,
                rows,
            ) in rows_by_table.items():
                for row in rows:
                    uploaded = upload_row_if_new(
                        s3_client,
                        bucket=bucket,
                        export_prefix=export_prefix,
                        document_id=document_id,
                        table_name=table_name,
                        row=row,
                    )

                    if uploaded:
                        uploaded_count += 1
                    else:
                        skipped_count += 1

    print(
        (
            "Data extraction completed successfully. "
            f"uploaded={uploaded_count}, "
            f"skipped_existing={skipped_count}"
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
