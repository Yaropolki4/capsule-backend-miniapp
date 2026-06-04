"""add item_link to outfits

Revision ID: b7d4f1e2a903
Revises: a3e8b2c91f54
Create Date: 2026-06-03 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b7d4f1e2a903'
down_revision: Union[str, None] = 'a3e8b2c91f54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outfits", sa.Column("item_link", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("outfits", "item_link")
