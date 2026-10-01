"""project_analyses keeps the model's validated choices

The engine now asks the model to choose among a bounded candidate set, and
replays that choice when the project is loaded. Without somewhere to put it, a
reload would rebuild the recommendation deterministically and could disagree
with the analysis the user was just shown.

``reasoning`` stores only what survived validation: the requirement role, the
product id the model picked, and its reason. Prices are never stored here and
never read from here — they are always read from the catalogue, so a stale
snapshot cannot become a price.

Revision ID: 0003_project_reasoning
Revises: 0002_catalog_json
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_project_reasoning"
down_revision: str | None = "0002_catalog_json"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "project_analyses",
        sa.Column(
            "reasoning",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("project_analyses", "reasoning")
