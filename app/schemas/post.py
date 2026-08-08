from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.core.post_status import PostStatus


class TagResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str


class PostBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    content: str = Field(..., min_length=1)
    excerpt: Optional[str] = Field(None, max_length=500)
    thumbnail: Optional[str] = Field(None, max_length=500)
    status: PostStatus = PostStatus.DRAFT
    published_at: Optional[datetime] = None


class PostCreate(PostBase):
    pass


class PostUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    content: Optional[str] = Field(None, min_length=1)
    excerpt: Optional[str] = Field(None, max_length=500)
    thumbnail: Optional[str] = Field(None, max_length=500)
    status: Optional[PostStatus] = None
    published_at: Optional[datetime] = None


class PostAuthor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class PostResponse(PostBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    author_id: int
    author: Optional[PostAuthor] = None
    tags: List[TagResponse] = []
    created_at: datetime
    updated_at: datetime


class PostListResponse(BaseModel):
    items: List[PostResponse]
    total: int
