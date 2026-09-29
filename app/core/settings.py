from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_host: str
    db_name: str
    db_username: str
    db_password: str

    s3_bucket_name: str
    s3_region: str

    sqs_queue_url: str
    redaction_sqs_queue_url: str | None = None

    auth_allowed_email_domains: str = "justice.gov.uk"

    auth_verification_token_ttl_minutes: int = 30
    auth_verification_cookie_name: str = "justice_redact_email_verification"

    auth_session_ttl_days: int = 7
    auth_session_cookie_name: str = "justice_redact_session"

    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = "lax"

    notify_api_key: str | None = None
    notify_verification_template_id: str | None = None

    auth_frontend_base_url: str = "http://localhost:3000"

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
