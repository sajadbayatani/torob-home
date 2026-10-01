"""Project requirements come from the interpreter, not from a template.

Three additive changes, nothing destroyed:

* ``project_analyses.template_id`` becomes nullable. A natural-language project
  is no longer required to match a rulebook, so a project with no template is a
  valid project. The tables themselves stay: they are still seeded and still
  usable for admin presets.

* ``project_analyses.template_id``'s foreign key changes from ``RESTRICT`` to
  ``SET NULL``, matching the model. A template that is deleted afterwards leaves
  the projects that consulted it as a preset intact, with a null link, instead of
  being blocked by a rulebook they no longer depend on.

* ``project_analyses.needs`` stores the requirements a project was actually
  built from, so a reload replays the user's own needs instead of re-reading a
  template that may have changed or may never have matched.

**The foreign key is found by introspection, not by name.** An earlier version of
this file dropped ``project_analyses_template_id_fkey`` and failed on every
database, because the real constraint is ``fk_project_analyses_template_id`` —
the name comes from ``MetaData(naming_convention)`` in ``app.db.base``. Asking
PostgreSQL which constraint points at ``project_templates`` cannot go stale that
way, and it also means this migration works on a database created from the models
(where the name is the convention's) and on one created by ``0001`` alike.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0004_project_needs"
down_revision = "0003_project_reasoning"
branch_labels = None
depends_on = None

#: The constraint this migration owns, and how it looked before and after.
_TABLE = "project_analyses"
_PARENT = "project_templates"


def _template_fk_name(bind) -> str | None:
    """
    The name of the ``project_analyses`` → ``project_templates`` foreign key.

    Matched on what the constraint *does* — its type, its table, and the table it
    points at — rather than on how it is spelled. Returns ``None`` when there is
    no such constraint, so the migration is a no-op on a database that does not
    have one rather than an error.
    """
    return bind.execute(
        sa.text(
            """
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace ns ON ns.oid = rel.relnamespace
            JOIN pg_attribute att
              ON att.attrelid = con.conrelid AND att.attnum = ANY(con.conkey)
            JOIN pg_class par ON par.oid = con.confrelid
            JOIN pg_namespace pns ON pns.oid = par.relnamespace
            WHERE con.contype = 'f'
              AND rel.relname = :table
              AND ns.nspname = current_schema()
              AND att.attname = :column
              AND par.relname = :parent
              AND pns.nspname = current_schema()
            """
        ),
        {"table": _TABLE, "column": "template_id", "parent": _PARENT},
    ).scalar()


def upgrade() -> None:
    bind = op.get_bind()

    name = _template_fk_name(bind)
    if name is not None:
        op.drop_constraint(name, _TABLE, type_="foreignkey")
        op.create_foreign_key(
            name, _TABLE, _PARENT, ["template_id"], ["id"], ondelete="SET NULL"
        )

    op.alter_column(
        _TABLE,
        "template_id",
        existing_type=sa.dialects.postgresql.UUID(),
        nullable=True,
    )

    # ``ProjectAnalysis.needs`` is declared ``Mapped[list]`` with no ``| None``,
    # so SQLAlchemy treats it as NOT NULL and the column is made NOT NULL here to
    # match — an always-present list is what the reader wants, and it removes the
    # question of what a null means. The server default is applied and then
    # dropped, so rows written before this migration land as ``[]`` — "this project
    # predates the snapshot" — rather than failing the NOT NULL.
    op.add_column(
        _TABLE,
        sa.Column(
            "needs",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.alter_column(_TABLE, "needs", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()

    op.drop_column(_TABLE, "needs")

    # A project with no template cannot be given a NOT NULL one, and silently
    # deleting or borrowing a template for it would be worse than refusing. The
    # count is reported so the operator knows what to look at.
    orphans = bind.execute(
        sa.text(f"SELECT count(*) FROM {_TABLE} WHERE template_id IS NULL")
    ).scalar()
    if orphans:
        raise RuntimeError(
            f"{orphans} project(s) have no template, so template_id cannot be made "
            "NOT NULL again. Assign a template to them, or delete them, before "
            "downgrading."
        )

    op.alter_column(
        _TABLE,
        "template_id",
        existing_type=sa.dialects.postgresql.UUID(),
        nullable=False,
    )

    name = _template_fk_name(bind)
    if name is not None:
        op.drop_constraint(name, _TABLE, type_="foreignkey")
        op.create_foreign_key(
            name, _TABLE, _PARENT, ["template_id"], ["id"], ondelete="RESTRICT"
        )
