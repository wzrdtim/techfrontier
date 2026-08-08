from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import and_, func, or_


class PostStatus(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SCHEDULED = "scheduled"
    ARCHIVED = "archived"


POST_STATUS_LABELS = {
    PostStatus.DRAFT: "Draft",
    PostStatus.PUBLISHED: "Published",
    PostStatus.SCHEDULED: "Scheduled",
    PostStatus.ARCHIVED: "Archived",
}

POST_STATUS_CHOICES = tuple(PostStatus)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def normalize_publish_fields(
    status: PostStatus | str,
    published_at: datetime | None,
) -> tuple[PostStatus, datetime | None]:
    """Normalize status + published_at for create/update."""
    value = PostStatus(status)
    now = utcnow()

    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    if published_at is not None:
        published_at = published_at.replace(microsecond=0)

    if value == PostStatus.PUBLISHED:
        if published_at is None:
            published_at = now
    elif value == PostStatus.SCHEDULED:
        if published_at is None:
            raise ValueError("Scheduled posts require a publish date")
        if published_at <= now:
            # Due date already passed — publish immediately.
            value = PostStatus.PUBLISHED
    return value, published_at


def live_posts_clause(model):
    """SQLAlchemy filter for posts that should appear on the public site."""
    now = func.now()
    return or_(
        model.status == PostStatus.PUBLISHED.value,
        and_(
            model.status == PostStatus.SCHEDULED.value,
            model.published_at.is_not(None),
            model.published_at <= now,
        ),
    )


def is_post_live(post) -> bool:
    now = utcnow()
    status = PostStatus(post.status)
    published_at = post.published_at
    if published_at is not None and published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)

    if status == PostStatus.PUBLISHED:
        return True
    if status == PostStatus.SCHEDULED:
        return published_at is not None and published_at <= now
    return False
