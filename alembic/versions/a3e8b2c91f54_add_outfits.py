"""add outfits

Revision ID: a3e8b2c91f54
Revises: f4cd59df3c47
Create Date: 2026-06-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3e8b2c91f54'
down_revision: Union[str, None] = 'f4cd59df3c47'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "outfits",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("item_title", sa.String(length=255), nullable=True),
        sa.Column("item_image_url", sa.String(), nullable=True),
        sa.Column("generated_image_url", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outfits_user_id"), "outfits", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_outfits_user_id"), table_name="outfits")
    op.drop_table("outfits")
