from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.post_status import (
    PostStatus,
    is_post_live,
    live_posts_clause,
    normalize_publish_fields,
)
from app.models.post import Post
from app.models.tag import Tag, post_tags
from app.schemas.post import PostCreate, PostUpdate

_IMAGE_LINE = re.compile(r"^!\[[^\]]*\]\([^)]+\)$")
_HTML_TAG = re.compile(r"<[^>]+>")


def _search_vector():
    """Weighted tsvector matching the GIN index on posts."""
    return (
        func.setweight(func.to_tsvector("english", func.coalesce(Post.title, "")), "A")
        .op("||")(
            func.setweight(
                func.to_tsvector("english", func.coalesce(Post.excerpt, "")),
                "B",
            )
        )
        .op("||")(
            func.setweight(
                func.to_tsvector("english", func.coalesce(Post.content, "")),
                "C",
            )
        )
    )


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^\w\s-]", "", value.lower())
    return re.sub(r"[-\s]+", "-", value).strip("-")


def plain_excerpt(content: str, limit: int = 200) -> str:
    text = content or ""
    if "<" in text and ">" in text:
        text = _HTML_TAG.sub(" ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit]

    parts = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block or _IMAGE_LINE.match(block):
            continue
        parts.append(block)
    return " ".join(parts)[:limit]


def _unique_slug(db: Session, title: str, exclude_id: int | None = None) -> str:
    base = slugify(title) or "post"
    slug = base
    counter = 1
    while True:
        query = select(Post).where(Post.slug == slug)
        if exclude_id is not None:
            query = query.where(Post.id != exclude_id)
        existing = db.execute(query).scalar_one_or_none()
        if existing is None:
            return slug
        slug = f"{base}-{counter}"
        counter += 1


class PostService:
    @staticmethod
    def list_posts(
        db: Session,
        *,
        skip: int = 0,
        limit: int = 20,
        published_only: bool = True,
        tag_slug: str | None = None,
    ) -> tuple[Sequence[Post], int]:
        filters = []
        if published_only:
            filters.append(live_posts_clause(Post))

        count_stmt = select(func.count()).select_from(Post)
        order_col = (
            func.coalesce(Post.published_at, Post.created_at).desc()
            if published_only
            else Post.updated_at.desc()
        )
        list_stmt = (
            select(Post)
            .options(joinedload(Post.author), joinedload(Post.tags))
            .order_by(order_col)
            .offset(skip)
            .limit(limit)
        )

        if tag_slug:
            count_stmt = (
                count_stmt.join(post_tags, Post.id == post_tags.c.post_id)
                .join(Tag, Tag.id == post_tags.c.tag_id)
                .where(Tag.slug == tag_slug)
            )
            list_stmt = (
                list_stmt.join(post_tags, Post.id == post_tags.c.post_id)
                .join(Tag, Tag.id == post_tags.c.tag_id)
                .where(Tag.slug == tag_slug)
            )

        if filters:
            count_stmt = count_stmt.where(*filters)
            list_stmt = list_stmt.where(*filters)

        total = db.execute(count_stmt).scalar_one()
        posts = db.execute(list_stmt).scalars().unique().all()
        return posts, total

    @staticmethod
    def search_posts(
        db: Session,
        query: str,
        *,
        skip: int = 0,
        limit: int = 20,
        published_only: bool = True,
    ) -> tuple[Sequence[Post], int]:
        q = " ".join(query.split())
        if not q:
            return [], 0

        vector = _search_vector()
        ts_query = func.websearch_to_tsquery("english", q)
        rank = func.ts_rank_cd(vector, ts_query)

        filters = [vector.op("@@")(ts_query)]
        if published_only:
            filters.append(live_posts_clause(Post))

        count_stmt = select(func.count()).select_from(Post).where(*filters)
        list_stmt = (
            select(Post)
            .options(joinedload(Post.author), joinedload(Post.tags))
            .where(*filters)
            .order_by(rank.desc(), func.coalesce(Post.published_at, Post.created_at).desc())
            .offset(skip)
            .limit(limit)
        )

        total = db.execute(count_stmt).scalar_one()
        posts = db.execute(list_stmt).scalars().unique().all()
        return posts, total

    @staticmethod
    def get_featured(db: Session, limit: int = 2) -> Sequence[Post]:
        """Most viewed live posts; falls back to newest when nothing has been clicked."""
        live = live_posts_clause(Post)
        clicked = db.execute(
            select(func.count())
            .select_from(Post)
            .where(live, Post.view_count > 0)
        ).scalar_one()

        order = (
            (Post.view_count.desc(), func.coalesce(Post.published_at, Post.created_at).desc())
            if clicked
            else (func.coalesce(Post.published_at, Post.created_at).desc(),)
        )
        stmt = (
            select(Post)
            .options(joinedload(Post.author), joinedload(Post.tags))
            .where(live)
            .order_by(*order)
            .limit(limit)
        )
        return db.execute(stmt).scalars().unique().all()

    @staticmethod
    def record_view(db: Session, post: Post) -> None:
        post.view_count = int(post.view_count or 0) + 1
        db.commit()
        db.refresh(post)

    @staticmethod
    def get_by_id(db: Session, post_id: int) -> Post | None:
        stmt = (
            select(Post)
            .options(joinedload(Post.author), joinedload(Post.tags))
            .where(Post.id == post_id)
        )
        return db.execute(stmt).unique().scalar_one_or_none()

    @staticmethod
    def get_by_slug(db: Session, slug: str) -> Post | None:
        stmt = (
            select(Post)
            .options(joinedload(Post.author), joinedload(Post.tags))
            .where(Post.slug == slug)
        )
        return db.execute(stmt).unique().scalar_one_or_none()

    @staticmethod
    def create(
        db: Session,
        data: PostCreate,
        author_id: int,
        tags: list[Tag] | None = None,
    ) -> Post:
        status, published_at = normalize_publish_fields(data.status, data.published_at)
        post = Post(
            title=data.title,
            slug=_unique_slug(db, data.title),
            excerpt=data.excerpt or plain_excerpt(data.content),
            content=data.content,
            thumbnail=data.thumbnail,
            status=status.value,
            published_at=published_at,
            author_id=author_id,
        )
        if tags:
            post.tags = tags
        db.add(post)
        db.commit()
        db.refresh(post)
        return PostService.get_by_id(db, post.id)  # type: ignore[return-value]

    @staticmethod
    def update(
        db: Session,
        post: Post,
        data: PostUpdate,
        tags: list[Tag] | None = None,
        update_tags: bool = False,
    ) -> Post:
        payload = data.model_dump(exclude_unset=True)
        if "title" in payload and payload["title"] != post.title:
            post.slug = _unique_slug(db, payload["title"], exclude_id=post.id)

        status = payload.pop("status", None)
        published_at = payload.pop("published_at", None)
        # Distinguish "not provided" vs "explicitly null" for published_at on PATCH.
        published_at_provided = "published_at" in data.model_fields_set

        for field, value in payload.items():
            setattr(post, field, value)

        next_status = PostStatus(status) if status is not None else PostStatus(post.status)
        if published_at_provided:
            next_published_at: datetime | None = published_at
        else:
            next_published_at = post.published_at

        if status is not None or published_at_provided:
            normalized_status, normalized_at = normalize_publish_fields(
                next_status,
                next_published_at,
            )
            post.status = normalized_status.value
            post.published_at = normalized_at

        if update_tags:
            post.tags = tags or []
        db.commit()
        db.refresh(post)
        return PostService.get_by_id(db, post.id)  # type: ignore[return-value]

    @staticmethod
    def delete(db: Session, post: Post) -> None:
        db.delete(post)
        db.commit()

    @staticmethod
    def is_live(post: Post) -> bool:
        return is_post_live(post)

    @staticmethod
    def count_posts(db: Session, *, published_only: bool = False) -> int:
        stmt = select(func.count()).select_from(Post)
        if published_only:
            stmt = stmt.where(live_posts_clause(Post))
        return db.execute(stmt).scalar_one()

    @staticmethod
    def total_views(db: Session) -> int:
        total = db.execute(select(func.coalesce(func.sum(Post.view_count), 0))).scalar_one()
        return int(total or 0)

    @staticmethod
    def recent_posts(db: Session, *, limit: int = 8) -> Sequence[Post]:
        stmt = (
            select(Post)
            .options(joinedload(Post.author), joinedload(Post.tags))
            .order_by(Post.updated_at.desc())
            .limit(limit)
        )
        return db.execute(stmt).scalars().unique().all()
