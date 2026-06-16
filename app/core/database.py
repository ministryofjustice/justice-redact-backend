from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import settings

DATABASE_URL = (
    f"postgresql+psycopg://"
    f"{settings.db_username}:"
    f"{settings.db_password}"
    f"@{settings.db_host}:5432/"
    f"{settings.db_name}"
)

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)
