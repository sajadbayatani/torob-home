"""Load the backend's reference data.

Only project templates and their requirement rules are seeded. **No product,
seller, price or offer is created here** — the product catalogue is
`data/catalog/products.json`, read by `app.catalog`, and the seed must never
shadow or duplicate it.

The command is idempotent: it upserts the templates by slug, so running it again
after a catalogue rebuild is a no-op.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.enums import ProjectType, Quality, QuantityMode
from app.db.session import get_session_factory
from app.domains.projects.models import ProjectRequirement, ProjectTemplate
from app.seed.dataset import PROJECT_TEMPLATES

SEED_NOW = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)

#: only the tables the seed owns
MANAGED_TABLES = ("project_requirements", "project_templates")


def wipe(session: Session) -> None:
    """Remove previously seeded reference data."""
    for requirement in session.scalars(select(ProjectRequirement)).all():
        session.delete(requirement)
    for template in session.scalars(select(ProjectTemplate)).all():
        session.delete(template)
    session.flush()


def seed(session: Session) -> dict[str, int]:
    """Upsert the project templates and their requirements."""
    templates = 0
    requirements = 0

    existing = {
        template.slug: template
        for template in session.scalars(select(ProjectTemplate)).all()
    }

    for entry in PROJECT_TEMPLATES:
        template = existing.get(entry["slug"])
        if template is None:
            template = ProjectTemplate(
                slug=entry["slug"],
                name_fa=entry["name_fa"],
                domain=entry["domain"],
                project_type=ProjectType(entry["project_type"]),
                description_fa=entry.get("description_fa"),
                keywords_fa=entry.get("keywords_fa", ""),
                default_area_m2=entry.get("default_area_m2"),
                default_quality=Quality(entry.get("default_quality", "medium")),
                is_active=True,
                created_at=SEED_NOW,
                updated_at=SEED_NOW,
            )
            session.add(template)
            session.flush()
        else:
            template.name_fa = entry["name_fa"]
            template.domain = entry["domain"]
            template.project_type = ProjectType(entry["project_type"])
            template.description_fa = entry.get("description_fa")
            template.keywords_fa = entry.get("keywords_fa", "")
            template.default_area_m2 = entry.get("default_area_m2")
            template.default_quality = Quality(entry.get("default_quality", "medium"))
            template.is_active = True
            template.updated_at = SEED_NOW
        templates += 1

        # replace this template's requirements wholesale: the rule set is
        # reference data, and a partial update would leave orphans behind
        for stale in session.scalars(
            select(ProjectRequirement).where(ProjectRequirement.template_id == template.id)
        ).all():
            session.delete(stale)
        session.flush()

        for rule in entry.get("requirements", []):
            session.add(
                ProjectRequirement(
                    template_id=template.id,
                    role=rule["role"],
                    category_slug=rule.get("category"),
                    quantity_mode=QuantityMode(rule["quantity_mode"]),
                    multiplier=rule["multiplier"],
                    min_qty=rule["min_qty"],
                    max_qty=rule.get("max_qty"),
                    quality_min=Quality(rule["quality_min"]),
                    style=rule.get("style"),
                    required=bool(rule["required"]),
                    reason_fa=rule.get("reason_fa", ""),
                    sort_order=int(rule.get("sort_order", 0)),
                )
            )
            requirements += 1
        session.flush()

    return {"templates": templates, "requirements": requirements}


def summary(session: Session) -> dict[str, int]:
    """Current row counts, so `--check` can report without writing."""
    return {
        "project_templates": int(
            session.scalar(select(func.count()).select_from(ProjectTemplate)) or 0
        ),
        "project_requirements": int(
            session.scalar(select(func.count()).select_from(ProjectRequirement)) or 0
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed the backend's reference data.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="report current counts only, without writing",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="remove the reference data instead of seeding it",
    )
    args = parser.parse_args()

    with get_session_factory()() as session:
        if args.check:
            print(summary(session))
            return
        if args.wipe:
            wipe(session)
            session.commit()
            print("reference data removed")
            return
        counts = seed(session)
        session.commit()
        counts.update(summary(session))
        counts["products"] = 0
        counts["note"] = (
            "The product catalogue is data/catalog/products.json and is never seeded."
        )
        print(counts)


if __name__ == "__main__":
    main()
