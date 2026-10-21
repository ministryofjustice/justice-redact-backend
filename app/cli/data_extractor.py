import os
import json
import boto3
import psycopg

def get_env_variable(name):
    val = os.getenv(name)
    if not val:
        raise ValueError(f"Required environment variable '{name}' is missing.")
    return val

def main():
    # 1. Load configuration from environment variables injected by Kubernetes secrets
    pghost = get_env_variable("PGHOST")
    pgdatabase = get_env_variable("PGDATABASE")
    pguser = get_env_variable("PGUSER")
    pgpassword = get_env_variable("PGPASSWORD")
    s3_destination = get_env_variable("S3_DESTINATION")
    aws_region = os.getenv("AWS_DEFAULT_REGION", "eu-west-2")

    print(f"Connecting to database {pgdatabase} at {pghost}...")

    # 2. Connect to PostgreSQL using Psycopg 3
    conn_info = f"host={pghost} dbname={pgdatabase} user={pguser} password={pgpassword} port=5432"
    
    s3_client = boto3.client("s3", region_name=aws_region)

    # Parse bucket and prefix from S3_DESTINATION (e.g., s3://bucket-name/path/)
    if s3_destination.startswith("s3://"):
        s3_path_no_scheme = s3_destination[5:]
        bucket_name, *prefix_parts = s3_path_no_scheme.split("/")
        s3_prefix = "/".join(prefix_parts)
    else:
        raise ValueError("S3_DESTINATION must start with 's3://'")

    with psycopg.connect(conn_info) as conn:
        with conn.cursor() as cur:
            # Fetch all user tables in the public schema
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema='public' AND table_type='BASE TABLE';
            """)
            tables = [row[0] for row in cur.fetchall()]
            print(f"Found tables to extract: {tables}")

            for table in tables:
                print(f"Extracting table: {table}...")
                jsonl_data = []
                
                # Stream rows safely in small batch chunks (10 rows) to protect memory
                cur.execute(f"SELECT * FROM {table};")
                
                while True:
                    rows = cur.fetchmany(10) # Batch chunk size of 10 rows
                    if not rows:
                        break
                    
                    colnames = [desc[0] for desc in cur.description]
                    for row in rows:
                        row_dict = dict(zip(colnames, row))
                        # Handle non-serializable types if any (like dates/UUIDs) by converting to string
                        for k, v in row_dict.items():
                            if v is not None and not isinstance(v, (int, float, bool, str)):
                                row_dict[k] = str(v)
                        jsonl_data.append(json.dumps(row_dict))

                # Compile into JSON lines format
                jsonl_content = "\n".join(jsonl_data)
                
                # Upload snapshot to S3 landing bucket
                s3_key = f"{s3_prefix}/{table}_snapshot.jsonl" if s3_prefix else f"{table}_snapshot.jsonl"
                print(f"Uploading {table} snapshot to s3://{bucket_name}/{s3_key}...")
                
                s3_client.put_object(
                    Bucket=bucket_name,
                    Key=s3_key,
                    Body=jsonl_content.encode('utf-8')
                )

    print("Data extraction and S3 upload completed successfully!")

if __name__ == "__main__":
    main()