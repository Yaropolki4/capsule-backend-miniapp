"""add messages

Revision ID: f4cd59df3c47
Revises: 8940c0478534
Create Date: 2026-06-01 10:59:39.119213

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4cd59df3c47'
down_revision: Union[str, None] = '8940c0478534'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("content_type", sa.String(length=32), nullable=False, server_default="text"),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_messages_user_id"), "messages", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_messages_user_id"), table_name="messages")
    op.drop_table("messages")
