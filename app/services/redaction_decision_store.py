from app.core.database import SessionLocal
from app.models.redaction_decision import RedactionDecision


def upsert_redaction_decisions(document_id: str, decisions_json: dict) -> None:
    with SessionLocal() as session:
        redaction_decision = session.get(RedactionDecision, document_id)

        if redaction_decision is None:
            redaction_decision = RedactionDecision(
                document_id=document_id,
                decisions_json=decisions_json,
            )
            session.add(redaction_decision)
        else:
            redaction_decision.decisions_json = decisions_json

        session.commit()


def get_redaction_decisions(document_id: str) -> dict | None:
    with SessionLocal() as session:
        redaction_decision = session.get(RedactionDecision, document_id)

        if redaction_decision is None:
            return None

        return redaction_decision.decisions_json
