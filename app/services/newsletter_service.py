from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.subscriber import Subscriber


class NewsletterService:
    @staticmethod
    def get_by_email(db: Session, email: str) -> Subscriber | None:
        return db.execute(
            select(Subscriber).where(Subscriber.email == email.lower())
        ).scalar_one_or_none()

    @staticmethod
    def count(db: Session) -> int:
        return db.execute(select(func.count()).select_from(Subscriber)).scalar_one()

    @staticmethod
    def list_subscribers(
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[list[Subscriber], int]:
        total = NewsletterService.count(db)
        rows = list(
            db.execute(
                select(Subscriber)
                .order_by(Subscriber.created_at.desc())
                .offset(skip)
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return rows, total

    @staticmethod
    def get_by_id(db: Session, subscriber_id: int) -> Subscriber | None:
        return db.execute(
            select(Subscriber).where(Subscriber.id == subscriber_id)
        ).scalar_one_or_none()

    @staticmethod
    def delete(db: Session, subscriber: Subscriber) -> None:
        db.delete(subscriber)
        db.commit()

    @staticmethod
    def subscribe(db: Session, email: str) -> tuple[Subscriber, bool]:
        normalized = email.strip().lower()
        existing = NewsletterService.get_by_email(db, normalized)
        if existing:
            return existing, False
        subscriber = Subscriber(email=normalized)
        db.add(subscriber)
        db.commit()
        db.refresh(subscriber)
        return subscriber, True
