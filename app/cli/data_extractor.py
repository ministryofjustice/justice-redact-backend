import os
import json
import boto3
import psycopg2

def extract_and_upload():
    # Connect to PostgreSQL using standard environment variables
    conn = psycopg2.connect(
        host=os.environ["PGHOST"],
        database=os.environ["PGDATABASE"],
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"]
    )
    cursor = conn.cursor()

    # 1. Extract table names
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema='public' AND table_type='BASE TABLE';
    """)
    tables = [row[0] for row in cursor.fetchall()]

    s3 = boto3.client(
        's3',
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
        region_name=os.environ.get("AWS_DEFAULT_REGION", "eu-west-2")
    )
    bucket_destination = os.environ["S3_DESTINATION"]

    os.makedirs("/db-exporter", exist_ok=True)

    for table in tables:
        print(f"Dumping table: {table}")
        cursor.execute(f"SELECT * FROM {table};")
        colnames = [desc[0] for desc in cursor.description]
        
        file_path = f"/db-exporter/{table}.jsonl"
        with open(file_path, "w") as f:
            while True:
                # Chunk size set to 10 rows to safeguard pod memory
                rows = cursor.fetchmany(10)
                if not rows:
                    break
                for row in rows:
                    obj = dict(zip(colnames, row))
                    f.write(json.dumps(obj, default=str) + "\n")

        # Upload to S3 destination bucket
        s3_key = f"snapshots/{table}.jsonl"
        print(f"Uploading {table}.jsonl to s3://{bucket_destination}/{s3_key}")
        s3.upload_file(file_path, bucket_destination, s3_key)

    cursor.close()
    conn.close()
    print("Data extraction and upload completed successfully.")

if __name__ == "__main__":
    extract_and_upload()