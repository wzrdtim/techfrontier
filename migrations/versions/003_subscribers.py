"""create subscribers table

Revision ID: 003_subscribers
Revises: 002_add_is_admin
Create Date: 2026-08-08 13:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_subscribers"
down_revision: Union[str, None] = "002_add_is_admin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subscribers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_subscribers_email"), "subscribers", ["email"], unique=True)
    op.create_index(op.f("ix_subscribers_id"), "subscribers", ["id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_subscribers_id"), table_name="subscribers")
    op.drop_index(op.f("ix_subscribers_email"), table_name="subscribers")
    op.drop_table("subscribers")
