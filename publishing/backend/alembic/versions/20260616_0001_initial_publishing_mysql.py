"""initial publishing tables

Revision ID: 20260616_0001
Revises:
Create Date: 2026-06-16
"""

from alembic import op


revision = "20260616_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.db import metadata

    metadata.create_all(op.get_bind())


def downgrade() -> None:
    from app.db import article_snapshots, assignments, publication_records, sessions, users

    for table in (publication_records, assignments, article_snapshots, sessions, users):
        table.drop(op.get_bind(), checkfirst=True)
