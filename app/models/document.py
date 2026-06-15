from sqlalchemy import Column, String, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = "documents"
    document_id = Column(String, primary_key=True)
    filename = Column(String, nullable=False)
    status = Column(String, nullable=False)
    subject_name = Column(Text, nullable=False, default="")
    subject_prison_number = Column(Text, nullable=False, default="")
    other_phrases = Column(Text, nullable=False, default="")
