from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class PageView(Base):
    __tablename__ = "page_views"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    path: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    visitor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    referrer: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    referrer_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    traffic_source: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        index=True,
        default="direct",
        server_default="direct",
    )
    country: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="ZZ",
        server_default="ZZ",
        index=True,
    )
    device: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="desktop",
        server_default="desktop",
        index=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(String(400), nullable=True)
    post_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    post = relationship("Post")
