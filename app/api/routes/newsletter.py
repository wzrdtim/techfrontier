from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.newsletter import NewsletterSubscribe, SubscriberResponse
from app.services.newsletter_service import NewsletterService

router = APIRouter(prefix="/newsletter", tags=["newsletter"])


@router.post("/subscribe", response_model=SubscriberResponse, status_code=status.HTTP_201_CREATED)
def subscribe(
    data: NewsletterSubscribe,
    db: Session = Depends(get_db),
) -> SubscriberResponse:
    subscriber, created = NewsletterService.subscribe(db, data.email)
    if not created:
        # Idempotent success for already-subscribed emails
        return SubscriberResponse.model_validate(subscriber)
    return SubscriberResponse.model_validate(subscriber)
