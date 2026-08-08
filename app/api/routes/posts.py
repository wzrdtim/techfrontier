from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.content import sanitize_html
from app.core.database import get_db
from app.models.user import User
from app.schemas.post import PostCreate, PostListResponse, PostResponse, PostUpdate
from app.services.auth_service import get_current_admin
from app.services.post_service import PostService

router = APIRouter(prefix="/posts", tags=["posts"])


def _sanitize_create(data: PostCreate) -> PostCreate:
    return data.model_copy(update={"content": sanitize_html(data.content)})


def _sanitize_update(data: PostUpdate) -> PostUpdate:
    if data.content is None:
        return data
    return data.model_copy(update={"content": sanitize_html(data.content)})


@router.get("", response_model=PostListResponse)
def list_posts(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    published_only: bool = True,
    db: Session = Depends(get_db),
) -> PostListResponse:
    posts, total = PostService.list_posts(
        db, skip=skip, limit=limit, published_only=published_only
    )
    return PostListResponse(
        items=[PostResponse.model_validate(p) for p in posts],
        total=total,
    )


@router.get("/{slug}", response_model=PostResponse)
def get_post(slug: str, db: Session = Depends(get_db)) -> PostResponse:
    post = PostService.get_by_slug(db, slug)
    if post is None or not PostService.is_live(post):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    return PostResponse.model_validate(post)


@router.post("", response_model=PostResponse, status_code=status.HTTP_201_CREATED)
def create_post(
    data: PostCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> PostResponse:
    post = PostService.create(db, _sanitize_create(data), author_id=admin.id)
    return PostResponse.model_validate(post)


@router.patch("/{post_id}", response_model=PostResponse)
def update_post(
    post_id: int,
    data: PostUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
) -> PostResponse:
    post = PostService.get_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    updated = PostService.update(db, post, _sanitize_update(data))
    return PostResponse.model_validate(updated)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_post(
    post_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    post = PostService.get_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found")
    PostService.delete(db, post)
