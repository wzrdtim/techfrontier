"""add page_views analytics

Revision ID: 009_page_views
Revises: 008_post_status
Create Date: 2026-08-08 14:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_page_views"
down_revision: Union[str, None] = "008_post_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "page_views",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("visitor_id", sa.String(length=64), nullable=False),
        sa.Column("referrer", sa.String(length=1000), nullable=True),
        sa.Column("referrer_host", sa.String(length=255), nullable=True),
        sa.Column("traffic_source", sa.String(length=40), nullable=False, server_default="direct"),
        sa.Column("country", sa.String(length=8), nullable=False, server_default="ZZ"),
        sa.Column("device", sa.String(length=20), nullable=False, server_default="desktop"),
        sa.Column("user_agent", sa.String(length=400), nullable=True),
        sa.Column("post_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_page_views_id", "page_views", ["id"])
    op.create_index("ix_page_views_path", "page_views", ["path"])
    op.create_index("ix_page_views_visitor_id", "page_views", ["visitor_id"])
    op.create_index("ix_page_views_referrer_host", "page_views", ["referrer_host"])
    op.create_index("ix_page_views_traffic_source", "page_views", ["traffic_source"])
    op.create_index("ix_page_views_country", "page_views", ["country"])
    op.create_index("ix_page_views_device", "page_views", ["device"])
    op.create_index("ix_page_views_post_id", "page_views", ["post_id"])
    op.create_index("ix_page_views_created_at", "page_views", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_page_views_created_at", table_name="page_views")
    op.drop_index("ix_page_views_post_id", table_name="page_views")
    op.drop_index("ix_page_views_device", table_name="page_views")
    op.drop_index("ix_page_views_country", table_name="page_views")
    op.drop_index("ix_page_views_traffic_source", table_name="page_views")
    op.drop_index("ix_page_views_referrer_host", table_name="page_views")
    op.drop_index("ix_page_views_visitor_id", table_name="page_views")
    op.drop_index("ix_page_views_path", table_name="page_views")
    op.drop_index("ix_page_views_id", table_name="page_views")
    op.drop_table("page_views")
