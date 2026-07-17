"""initial writing mysql tables

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
    from app.storage.mysql_schema import metadata

    metadata.create_all(op.get_bind())


def downgrade() -> None:
    from app.storage.mysql_schema import (
        writing_articles,
        writing_content_items,
        writing_custom_sources,
        writing_jobs,
        writing_logs,
        writing_materials,
        writing_matrix_import_drafts,
        writing_projects,
        writing_steps,
    )

    for table in (
        writing_logs,
        writing_matrix_import_drafts,
        writing_articles,
        writing_content_items,
        writing_jobs,
        writing_steps,
        writing_custom_sources,
        writing_materials,
        writing_projects,
    ):
        table.drop(op.get_bind(), checkfirst=True)
