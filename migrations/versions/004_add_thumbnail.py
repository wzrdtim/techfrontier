"""add thumbnail to posts

Revision ID: 004_add_thumbnail
Revises: 003_subscribers
Create Date: 2026-08-08 13:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_add_thumbnail"
down_revision: Union[str, None] = "003_subscribers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("thumbnail", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "thumbnail")
