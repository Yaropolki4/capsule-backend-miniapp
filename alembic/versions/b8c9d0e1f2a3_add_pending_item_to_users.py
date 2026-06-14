"""add pending_item_id to users

Revision ID: b8c9d0e1f2a3
Revises: d3e4f5a6b7c8
Create Date: 2026-06-14 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('pending_item_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'pending_item_id')
