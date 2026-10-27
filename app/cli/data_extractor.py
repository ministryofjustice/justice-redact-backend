# import os
# import json
# import boto3
# import psycopg

# def get_env_variable(name):
#     val = os.getenv(name)
#     if not val:
#         raise ValueError(f"Required environment variable '{name}' is missing.")
#     return val

# def main():
#     pghost = get_env_variable("PGHOST")
#     pgdatabase = get_env_variable("PGDATABASE")
#     pguser = get_env_variable("PGUSER")
#     pgpassword = get_env_variable("PGPASSWORD")
#     s3_destination = get_env_variable("S3_DESTINATION")
#     aws_region = os.getenv("AWS_DEFAULT_REGION", "eu-west-2")

#     print(f"Connecting to database {pgdatabase} at {pghost}...")

#     conn_info = f"host={pghost} dbname={pgdatabase} user={pguser} password={pgpassword} port=5432"
#     s3_client = boto3.client("s3", region_name=aws_region)

#     # Safely parse bucket and clean prefix from S3_DESTINATION, avoiding double slashes
#     if s3_destination.startswith("s3://"):
#         s3_path_no_scheme = s3_destination[5:]
#         parts = s3_path_no_scheme.split("/", 1)
#         bucket_name = parts[0]
#         s3_prefix = parts[1].strip("/") if len(parts) > 1 and parts[1] else ""
#     else:
#         raise ValueError("S3_DESTINATION must start with 's3://'")

#     with psycopg.connect(conn_info) as conn:
#         with conn.cursor() as cur:
#             # Fetch all user tables explicitly in the public schema
#             cur.execute("""
#                 SELECT table_name
#                 FROM information_schema.tables
#                 WHERE table_schema='public' AND table_type='BASE TABLE';
#             """)
#             tables = [row[0] for row in cur.fetchall()]
#             print(f"Found tables to extract: {tables}")

#             for table in tables:
#                 print(f"Extracting table: {table}...")
#                 jsonl_data = []

#                 # Explicitly qualify table schema to prevent ambiguity errors
#                 cur.execute(f"SELECT * FROM public.{table};")

#                 # Use a safe batch chunk size of 20 rows to prevent OOM spikes
#                 while True:
#                     rows = cur.fetchmany(20)
#                     if not rows:
#                         break

#                     colnames = [desc[0] for desc in cur.description]
#                     for row in rows:
#                         row_dict = dict(zip(colnames, row))
#                         jsonl_data.append(json.dumps(row_dict, default=str))

#                 jsonl_content = "\n".join(jsonl_data)

#                 # Construct clean S3 key without double slashes
#                 s3_key = f"{s3_prefix}/{table}_snapshot.jsonl" if s3_prefix else f"{table}_snapshot.jsonl"
#                 print(f"Uploading {table} snapshot to s3://{bucket_name}/{s3_key}...")

#                 s3_client.put_object(
#                     Bucket=bucket_name,
#                     Key=s3_key,
#                     Body=jsonl_content.encode('utf-8')
#                 )

#     print("Data extraction and S3 upload completed successfully!")

# if __name__ == "__main__":
#     main()

import os
import uuid
import boto3
from botocore.exceptions import ClientError


def main():
    destination = os.environ["S3_DESTINATION"]
    role_arn = os.environ["AP_S3_ROLE_ARN"]

    region = os.getenv("AWS_DEFAULT_REGION", "eu-west-2")

    if not destination.startswith("s3://"):
        raise ValueError("S3_DESTINATION must start with s3://")

    bucket, _, prefix = destination[5:].partition("/")
    key = f"{prefix.strip('/')}/access-test-{uuid.uuid4().hex}.txt".lstrip("/")

    print(f"Assuming Analytical Platform S3 role: {role_arn}")

    sts = boto3.client("sts", region_name=region)
    assumed_role = sts.assume_role(
        RoleArn=role_arn,
        RoleSessionName="justice-redact-data-extractor",
    )

    credentials = assumed_role["Credentials"]

    s3 = boto3.client(
        "s3",
        region_name=region,
        aws_access_key_id=credentials["AccessKeyId"],
        aws_secret_access_key=credentials["SecretAccessKey"],
        aws_session_token=credentials["SessionToken"],
    )
    content = b"S3 access test"

    print(f"Testing S3 access: s3://{bucket}/{key}")

    # Test WRITE permission
    s3.put_object(Bucket=bucket, Key=key, Body=content)
    print("PASS: S3 write access")

    try:
        # Test READ permission
        response = s3.get_object(Bucket=bucket, Key=key)
        assert response["Body"].read() == content
        print("PASS: S3 read access")
    finally:
        # Cleanup (DELETE permission is optional)
        try:
            s3.delete_object(Bucket=bucket, Key=key)
            print("PASS: Test object deleted")
        except ClientError as e:
            print(f"WARNING: Could not delete test object: {e}")

    print("S3 read/write test completed successfully")


if __name__ == "__main__":
    main()
