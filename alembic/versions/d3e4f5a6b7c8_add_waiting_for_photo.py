"""add waiting_for_photo to users

Revision ID: d3e4f5a6b7c8
Revises: e2f8a3d5c9b1, b7d4f1e2a903
Create Date: 2026-06-09 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, tuple, None] = ('e2f8a3d5c9b1', 'b7d4f1e2a903')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('waiting_for_photo', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('users', 'waiting_for_photo')
