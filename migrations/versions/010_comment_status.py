"""add comment moderation status

Revision ID: 010_comment_status
Revises: 009_page_views
Create Date: 2026-08-08 14:45:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_comment_status"
down_revision: Union[str, None] = "009_page_views"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "comments",
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="pending",
        ),
    )
    op.create_index("ix_comments_status", "comments", ["status"])
    # Existing comments were already public — keep them approved.
    op.execute("UPDATE comments SET status = 'approved'")


def downgrade() -> None:
    op.drop_index("ix_comments_status", table_name="comments")
    op.drop_column("comments", "status")
