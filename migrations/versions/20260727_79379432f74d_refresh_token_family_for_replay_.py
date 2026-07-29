"""refresh token family for replay detection

Adds ``refresh_tokens.family_id`` so that replaying a consumed refresh token
can revoke every descendant token instead of only the presented one.

Revision ID: 79379432f74d
Revises: bb2fc50762e5
Create Date: 2026-07-27 14:33:36.629677
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "79379432f74d"
down_revision: str | None = "bb2fc50762e5"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # Three steps, because the table already holds rows in any live
    # environment and a bare NOT NULL add would abort the deploy:
    #   1. add the column nullable,
    #   2. backfill - each existing token becomes its own single-member
    #      family, which preserves current sessions while making replay
    #      detection effective from the next rotation onward,
    #   3. tighten to NOT NULL.
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.add_column(sa.Column("family_id", sa.String(length=36), nullable=True))

    op.execute("UPDATE refresh_tokens SET family_id = id WHERE family_id IS NULL")

    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.alter_column(
            "family_id", existing_type=sa.String(length=36), nullable=False
        )
        batch_op.create_index(
            batch_op.f("ix_refresh_tokens_family_id"), ["family_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("refresh_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_refresh_tokens_family_id"))
        batch_op.drop_column("family_id")
