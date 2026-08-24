from app.core.database import SessionLocal
from datetime import datetime, timezone
from sqlalchemy import select
from app.models.document import Document
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


def save_redaction_decisions(
    *,
    document_id: str,
    decisions_json: dict,
    expected_revision: int,
) -> dict:
    with SessionLocal() as session:
        session.execute(
            select(Document.document_id)
            .where(Document.document_id == document_id)
            .with_for_update()
        ).scalar_one_or_none()

        redaction_decision = session.execute(
            select(RedactionDecision)
            .where(RedactionDecision.document_id == document_id)
            .with_for_update()
        ).scalar_one_or_none()

        if redaction_decision is None:
            if expected_revision != 0:
                return {
                    "saved": False,
                    "revision": 0,
                }

            redaction_decision = RedactionDecision(
                document_id=document_id,
                decisions_json=decisions_json,
                revision=1,
                updated_at=datetime.now(timezone.utc),
            )

            session.add(redaction_decision)
            session.commit()

            return {
                "saved": True,
                "revision": 1,
            }

        if redaction_decision.revision != expected_revision:
            return {
                "saved": False,
                "revision": redaction_decision.revision,
            }

        if redaction_decision.decisions_json == decisions_json:
            return {
                "saved": True,
                "revision": redaction_decision.revision,
            }

        redaction_decision.decisions_json = decisions_json
        redaction_decision.revision += 1
        redaction_decision.updated_at = datetime.now(timezone.utc)

        session.commit()

        return {
            "saved": True,
            "revision": redaction_decision.revision,
        }


def get_redaction_decision_state(
    document_id: str,
) -> dict:
    with SessionLocal() as session:
        redaction_decision = session.get(
            RedactionDecision,
            document_id,
        )

        if redaction_decision is None:
            return {
                "documentId": document_id,
                "revision": 0,
                "decisions": [],
                "updatedAt": None,
            }

        decisions_json = redaction_decision.decisions_json

        return {
            "documentId": document_id,
            "revision": redaction_decision.revision,
            "decisions": decisions_json.get(
                "decisions",
                [],
            ),
            "updatedAt": (
                redaction_decision.updated_at.isoformat()
                if redaction_decision.updated_at
                else None
            ),
        }


def get_redaction_decisions(document_id: str) -> dict | None:
    with SessionLocal() as session:
        redaction_decision = session.get(RedactionDecision, document_id)

        if redaction_decision is None:
            return None

        return redaction_decision.decisions_json
