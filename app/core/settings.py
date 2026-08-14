from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    db_host: str
    db_name: str
    db_username: str
    db_password: str

    s3_bucket_name: str
    s3_region: str

    sqs_queue_url: str

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )


settings = Settings()
