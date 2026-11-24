from pydantic import BaseModel


class RequestVerificationRequest(BaseModel):
    email: str


class VerifyEmailRequest(BaseModel):
    token: str
