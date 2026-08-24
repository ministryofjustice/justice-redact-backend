import os


os.environ.setdefault(
    "SQS_QUEUE_URL",
    "http://localhost:4566/000000000000/justice-redact-test",
)

os.environ.setdefault(
    "REDACTION_SQS_QUEUE_URL",
    "http://localhost:4566/000000000000/justice-redact-redaction-test",
)
