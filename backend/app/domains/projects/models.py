"""Project (need) domain models: templates, rule-based requirements, analyses."""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import DataSource, Domain, ProjectType, Quality, QuantityMode
from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

# Imported for real, not under TYPE_CHECKING: `ProjectAnalysis.basket` is a
# relationship to a string, and SQLAlchemy resolves it from the class registry,
# so the target class must be imported before this module is configured. The
# basket models do not import this module, so there is no cycle.
from app.domains.basket.models import Basket  # noqa: E402

Enum = SAEnum


class ProjectTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A reusable "type of job", e.g. «بازسازی سرویس بهداشتی»."""

    __tablename__ = "project_templates"

    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name_fa: Mapped[str] = mapped_column(String(160))
    domain: Mapped[Domain] = mapped_column(Enum(Domain, name="domain_enum"), index=True)
    project_type: Mapped[ProjectType] = mapped_column(
        Enum(ProjectType, name="project_type_enum"), index=True
    )
    description_fa: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords_fa: Mapped[str] = mapped_column(Text, default="")
    default_area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    default_quality: Mapped[Quality] = mapped_column(
        Enum(Quality, name="quality_enum"), default=Quality.MEDIUM
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    requirements: Mapped[list[ProjectRequirement]] = relationship(
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="ProjectRequirement.sort_order",
    )


class ProjectRequirement(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One deterministic rule inside a template.

    Example: ``role=tiles, category=bathroom.tiles, quantity_mode=per_area,
    multiplier=3.2`` -> a 12 m² bathroom needs ~39 m² of tile.
    """

    __tablename__ = "project_requirements"
    __table_args__ = (UniqueConstraint("template_id", "role", name="uq_requirement_template_role"),)

    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("project_templates.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(60), index=True)
    #: a catalogue subcategory slug (``products.json``'s vocabulary), not a
    #: foreign key: the catalogue is a file, so a requirement addresses it by name
    category_slug: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    quantity_mode: Mapped[QuantityMode] = mapped_column(
        Enum(QuantityMode, name="quantity_mode_enum"), default=QuantityMode.FIXED
    )
    multiplier: Mapped[Decimal] = mapped_column(Numeric(8, 3), default=Decimal("1"))
    min_qty: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0"))
    max_qty: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    quality_min: Mapped[Quality] = mapped_column(
        Enum(Quality, name="quality_enum"), default=Quality.LOW
    )
    style: Mapped[str | None] = mapped_column(String(40), nullable=True)
    required: Mapped[bool] = mapped_column(Boolean, default=True)
    reason_fa: Mapped[str] = mapped_column(String(300), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    template: Mapped[ProjectTemplate] = relationship(back_populates="requirements")


class ProjectAnalysis(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A concrete interpretation of one need query + the basket it produced.

    ``requirements`` is a JSONB *snapshot of the interpreter output* (this is the
    only place JSON is used: the LLM payload is stored verbatim for audit and
    re-display). Catalogue relationships stay relational.
    """

    __tablename__ = "project_analyses"

    #: The matching project template, when one exists. **Optional, and not what
    #: defines the project.** A natural-language project is built from the
    #: interpreter's own requirements, which are stored in ``needs`` below; a
    #: template is a preset consulted for quantity rules and a label. The
    #: foreign key stays because the tables are still seeded and still useful for
    #: admin and future presets — it is simply no longer load-bearing.
    template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("project_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    basket_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("baskets.id", ondelete="SET NULL"), nullable=True, unique=True
    )
    title_fa: Mapped[str] = mapped_column(String(200))
    original_query: Mapped[str] = mapped_column(Text)
    area_m2: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    quality: Mapped[Quality] = mapped_column(
        Enum(Quality, name="quality_enum"), default=Quality.MEDIUM
    )
    style: Mapped[str | None] = mapped_column(String(40), nullable=True)
    budget: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Toman
    requirements: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: The project's requirements exactly as they were resolved from the
    #: interpreter: description, catalogue subcategories, quantity, floor.
    #:
    #: This is what a reload replays. It used to re-read the template's rules, so
    #: a stored project showed whatever the rulebook said rather than what this
    #: user asked for — and a project whose template could not be resolved could
    #: not be shown at all.
    needs: Mapped[list] = mapped_column(JSONB, default=list)
    intent_payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    #: the model's validated choices for this project, keyed by requirement role.
    #: Holds ids and reasons only — never a price, which always comes from the
    #: catalogue — so a reload reproduces the analysis instead of re-deriving one
    #: that may disagree with it.
    reasoning: Mapped[dict] = mapped_column(JSONB, default=dict)
    estimated_total: Mapped[int] = mapped_column(Integer, default=0)  # Toman
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), default=Decimal("0.800"))
    interpreter: Mapped[str] = mapped_column(String(40), default="rules")
    data_source: Mapped[DataSource] = mapped_column(
        Enum(DataSource, name="data_source_enum"), default=DataSource.SEED
    )

    template: Mapped[ProjectTemplate] = relationship()
    basket: Mapped[Basket | None] = relationship(foreign_keys=[basket_id])
