from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    String,
    UniqueConstraint,
    false,
)
from sqlalchemy.sql import func

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    __table_args__ = (
        UniqueConstraint(
            "email",
            name="uq_users_email",
        ),
    )

    user_id = Column(
        String,
        primary_key=True,
    )

    email = Column(
        String,
        nullable=False,
    )

    access_enabled = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )

    created_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    last_verified_at = Column(
        DateTime(timezone=True),
        nullable=True,
    )
