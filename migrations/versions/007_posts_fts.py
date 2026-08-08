"""add posts full-text search index

Revision ID: 007_posts_fts
Revises: 006_views_comments
Create Date: 2026-08-08 14:15:00.000000

"""

from typing import Sequence, Union

from alembic import op

revision: str = "007_posts_fts"
down_revision: Union[str, None] = "006_views_comments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_posts_fts
        ON posts
        USING gin (
          (
            setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
            setweight(to_tsvector('english', coalesce(excerpt, '')), 'B') ||
            setweight(to_tsvector('english', coalesce(content, '')), 'C')
          )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_posts_fts")
