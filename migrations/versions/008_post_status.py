"""add post status and published_at

Revision ID: 008_post_status
Revises: 007_posts_fts
Create Date: 2026-08-08 14:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_post_status"
down_revision: Union[str, None] = "007_posts_fts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        "posts",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_posts_status", "posts", ["status"])
    op.create_index("ix_posts_published_at", "posts", ["published_at"])

    op.execute(
        """
        UPDATE posts
        SET
          status = CASE WHEN published THEN 'published' ELSE 'draft' END,
          published_at = CASE WHEN published THEN created_at ELSE NULL END
        """
    )
    op.drop_column("posts", "published")


def downgrade() -> None:
    op.add_column(
        "posts",
        sa.Column(
            "published",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.execute(
        """
        UPDATE posts
        SET published = CASE
          WHEN status IN ('published', 'scheduled') THEN true
          ELSE false
        END
        """
    )
    op.drop_index("ix_posts_published_at", table_name="posts")
    op.drop_index("ix_posts_status", table_name="posts")
    op.drop_column("posts", "published_at")
    op.drop_column("posts", "status")
