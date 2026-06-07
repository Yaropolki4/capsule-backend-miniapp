"""add stars to outfits

Revision ID: e2f8a3d5c9b1
Revises: b7d4f1e2a903
Create Date: 2026-06-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e2f8a3d5c9b1'
down_revision: Union[str, None] = 'b7d4f1e2a903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("outfits", sa.Column("stars", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("outfits", "stars")
