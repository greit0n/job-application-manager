"""Application packet workflow and Gmail draft support.

Revision ID: 9b1d2c3e4f50
Revises: e2f1a7c9b3d4
Create Date: 2026-06-24
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "9b1d2c3e4f50"
down_revision = "e2f1a7c9b3d4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "applications",
        sa.Column("application_channel", sa.String(length=40), nullable=False, server_default="email"),
    )
    op.add_column(
        "applications",
        sa.Column("recipient_name", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "applications",
        sa.Column("recipient_email", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "applications",
        sa.Column("next_action", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column("applications", sa.Column("follow_up_date", sa.Date(), nullable=True))
    op.add_column("applications", sa.Column("last_activity_at", sa.Date(), nullable=True))
    op.add_column(
        "applications",
        sa.Column("gmail_draft_id", sa.String(length=255), nullable=False, server_default=""),
    )
    op.add_column(
        "applications",
        sa.Column("gmail_drafted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        "gmail_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("gmail_email", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("access_token_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=False, server_default=""),
        sa.Column("token_type", sa.String(length=40), nullable=False, server_default="Bearer"),
        sa.Column("scope", sa.Text(), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_gmail_connections_user_id"), "gmail_connections", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_gmail_connections_user_id"), table_name="gmail_connections")
    op.drop_table("gmail_connections")
    op.drop_column("applications", "gmail_drafted_at")
    op.drop_column("applications", "gmail_draft_id")
    op.drop_column("applications", "last_activity_at")
    op.drop_column("applications", "follow_up_date")
    op.drop_column("applications", "next_action")
    op.drop_column("applications", "recipient_email")
    op.drop_column("applications", "recipient_name")
    op.drop_column("applications", "application_channel")
