from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DB_HOST = __import__("os").environ["DB_HOST"]
DB_NAME = __import__("os").environ["DB_NAME"]
DB_USERNAME = __import__("os").environ["DB_USERNAME"]
DB_PASSWORD = __import__("os").environ["DB_PASSWORD"]

DATABASE_URL = (
    f"postgresql+psycopg://{DB_USERNAME}:{DB_PASSWORD}" f"@{DB_HOST}:5432/{DB_NAME}"
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
