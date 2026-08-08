from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.tag import Tag, post_tags
from app.services.post_service import slugify

DEFAULT_TAGS = (
    ("AI", "ai"),
    ("Technology", "technology"),
    ("Analys", "analys"),
)


class TagService:
    @staticmethod
    def list_tags(db: Session) -> list[Tag]:
        return list(db.execute(select(Tag).order_by(Tag.name)).scalars().all())

    @staticmethod
    def list_with_counts(db: Session) -> list[tuple[Tag, int]]:
        rows = db.execute(
            select(Tag, func.count(post_tags.c.post_id))
            .outerjoin(post_tags, Tag.id == post_tags.c.tag_id)
            .group_by(Tag.id)
            .order_by(Tag.name)
        ).all()
        return [(tag, int(count or 0)) for tag, count in rows]

    @staticmethod
    def get_by_slug(db: Session, slug: str) -> Tag | None:
        return db.execute(select(Tag).where(Tag.slug == slug)).scalar_one_or_none()

    @staticmethod
    def get_by_id(db: Session, tag_id: int) -> Tag | None:
        return db.execute(select(Tag).where(Tag.id == tag_id)).scalar_one_or_none()

    @staticmethod
    def get_by_ids(db: Session, tag_ids: list[int]) -> list[Tag]:
        if not tag_ids:
            return []
        return list(
            db.execute(select(Tag).where(Tag.id.in_(tag_ids))).scalars().all()
        )

    @staticmethod
    def create(db: Session, name: str) -> Tag:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("Tag name is required")
        base_slug = slugify(cleaned) or "tag"
        slug = base_slug
        counter = 1
        while TagService.get_by_slug(db, slug) is not None:
            slug = f"{base_slug}-{counter}"
            counter += 1
        tag = Tag(name=cleaned[:50], slug=slug[:60])
        db.add(tag)
        db.commit()
        db.refresh(tag)
        return tag

    @staticmethod
    def delete(db: Session, tag: Tag) -> None:
        db.delete(tag)
        db.commit()

    @staticmethod
    def ensure_default_tags(db: Session) -> None:
        for name, slug in DEFAULT_TAGS:
            existing = TagService.get_by_slug(db, slug)
            if existing is None:
                db.add(Tag(name=name, slug=slug))
        db.commit()
