"""Add cv_variants.extracted_text; drop profile content fields.

The uploaded CV is now the source of truth for experience, so the duplicated
headline/skills/summary/employers profile fields are removed. Dropping
`employers` permanently discards its data (intended).

Revision ID: e2f1a7c9b3d4
Revises: fdfc27938220
Create Date: 2026-06-23
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "e2f1a7c9b3d4"
down_revision = "fdfc27938220"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cv_variants",
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
    )
    op.drop_column("profiles", "headline")
    op.drop_column("profiles", "skills")
    op.drop_column("profiles", "summary")
    op.drop_column("profiles", "employers")


def downgrade() -> None:
    op.add_column(
        "profiles",
        sa.Column("employers", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "profiles",
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "profiles",
        sa.Column("skills", sa.Text(), nullable=False, server_default=""),
    )
    op.add_column(
        "profiles",
        sa.Column("headline", sa.String(length=255), nullable=False, server_default=""),
    )
    op.drop_column("cv_variants", "extracted_text")
