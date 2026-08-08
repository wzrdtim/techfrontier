from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.contact_message import ContactMessage


class ContactService:
    @staticmethod
    def create(
        db: Session,
        *,
        email: str,
        subject: str,
        body: str,
    ) -> ContactMessage:
        message = ContactMessage(
            email=email.strip().lower()[:255],
            subject=subject.strip()[:200],
            body=body.strip(),
            is_read=False,
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message

    @staticmethod
    def list_recent(
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[ContactMessage], int]:
        total = db.execute(select(func.count()).select_from(ContactMessage)).scalar_one()
        messages = list(
            db.execute(
                select(ContactMessage)
                .order_by(ContactMessage.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return messages, total

    @staticmethod
    def count_unread(db: Session) -> int:
        return db.execute(
            select(func.count())
            .select_from(ContactMessage)
            .where(ContactMessage.is_read.is_(False))
        ).scalar_one()

    @staticmethod
    def get_by_id(db: Session, message_id: int) -> ContactMessage | None:
        return db.execute(
            select(ContactMessage).where(ContactMessage.id == message_id)
        ).scalar_one_or_none()

    @staticmethod
    def mark_read(db: Session, message: ContactMessage) -> ContactMessage:
        message.is_read = True
        db.add(message)
        db.commit()
        db.refresh(message)
        return message

    @staticmethod
    def delete(db: Session, message: ContactMessage) -> None:
        db.delete(message)
        db.commit()
