from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models.comment import Comment, CommentStatus


class CommentService:
    @staticmethod
    def list_for_post(db: Session, post_id: int) -> list[Comment]:
        return list(
            db.execute(
                select(Comment)
                .where(
                    Comment.post_id == post_id,
                    Comment.status == CommentStatus.APPROVED.value,
                )
                .order_by(Comment.created_at.asc())
            )
            .scalars()
            .all()
        )

    @staticmethod
    def list_recent(
        db: Session,
        *,
        status: CommentStatus | str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Comment], int]:
        query = select(Comment).options(joinedload(Comment.post))
        count_query = select(func.count()).select_from(Comment)
        if status is not None:
            value = CommentStatus(status).value
            query = query.where(Comment.status == value)
            count_query = count_query.where(Comment.status == value)

        total = db.execute(count_query).scalar_one()
        comments = list(
            db.execute(
                query.order_by(Comment.created_at.desc()).offset(skip).limit(limit)
            )
            .scalars()
            .unique()
            .all()
        )
        return comments, total

    @staticmethod
    def count(db: Session) -> int:
        return db.execute(select(func.count()).select_from(Comment)).scalar_one()

    @staticmethod
    def count_by_status(db: Session, status: CommentStatus | str) -> int:
        value = CommentStatus(status).value
        return db.execute(
            select(func.count())
            .select_from(Comment)
            .where(Comment.status == value)
        ).scalar_one()

    @staticmethod
    def get_by_id(db: Session, comment_id: int) -> Comment | None:
        return (
            db.execute(
                select(Comment)
                .options(joinedload(Comment.post))
                .where(Comment.id == comment_id)
            )
            .unique()
            .scalar_one_or_none()
        )

    @staticmethod
    def set_status(db: Session, comment: Comment, status: CommentStatus | str) -> Comment:
        comment.status = CommentStatus(status).value
        db.add(comment)
        db.commit()
        db.refresh(comment)
        return comment

    @staticmethod
    def delete(db: Session, comment: Comment) -> None:
        db.delete(comment)
        db.commit()

    @staticmethod
    def create(db: Session, *, post_id: int, name: str, email: str, body: str) -> Comment:
        comment = Comment(
            post_id=post_id,
            name=name.strip()[:100],
            email=email.strip().lower()[:255],
            body=body.strip(),
            status=CommentStatus.PENDING.value,
        )
        db.add(comment)
        db.commit()
        db.refresh(comment)
        return comment
