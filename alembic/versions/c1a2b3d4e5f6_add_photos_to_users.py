"""add photos to users

Revision ID: c1a2b3d4e5f6
Revises: b7d4f1e2a903
Create Date: 2026-06-03 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'c1a2b3d4e5f6'
down_revision: Union[str, None] = 'b7d4f1e2a903'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("photos", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "photos")
