"""Baseline: état complet du schéma (idempotent, identique à manage.py install-schema).

Revision ID: 0001
Revises:
Create Date: 2026-09-21

"""
from alembic import op

from app.core.schema import SCHEMA_SQL

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Le SQL est idempotent (IF NOT EXISTS / DO blocks) -> sûr sur une DB
    # bootstrapée par `manage.py install-schema` (aucun no-op en double).
    op.execute(SCHEMA_SQL)


def downgrade() -> None:
    raise NotImplementedError(
        "La baseline v1 ne supporte pas le downgrade "
        "(détrez les objets manuellement si nécessaire)."
    )
