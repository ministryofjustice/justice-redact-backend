from pydantic import BaseModel


class ProcessDocumentRequest(BaseModel):
    subjectName: str = ""
    subjectPrisonNumber: str = ""
    otherPhrases: str = ""
