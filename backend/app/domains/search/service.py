"""Search domain service: interpreter wiring + catalogue enrichment.

Enrichment is the *only* place where interpreter output meets the catalogue, and
it can only ever **resolve references** — a brand name, a subcategory slug, a
project template. It never creates catalogue data. Brands and subcategories are
resolved against `data/catalog/products.json`; project templates are still
reference data in the database.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.enums import Domain, ProjectType, domain_from
from app.core.text import normalize_persian
from app.domains.projects.models import ProjectTemplate
from app.domains.search.interpreter import IntentInterpreter
from app.domains.search.llm_interpreter import LLMInterpreter
from app.domains.search.schemas import InterpretedIntent


def build_interpreter(settings: Settings | None = None) -> IntentInterpreter:
    """
    The interpreter is the LLM.

    There is deliberately no second provider to fall back to. A keyword
    interpreter would answer with the same confidence whether or not it
    understood the sentence, which is the behaviour this replaced.
    """
    from app.core.config import get_settings

    return LLMInterpreter(settings or get_settings())


class SearchService:
    def __init__(self, interpreter: IntentInterpreter | None = None) -> None:
        self._interpreter = interpreter

    @property
    def interpreter_name(self) -> str:
        return self._interpreter.name if self._interpreter else LLMInterpreter.name

    # ------------------------------------------------------------------ #
    def route(self, query: str):
        """
        Decide where a query goes, from the catalogue, with no model involved.

        This is the first thing the system does with a search, and it is
        deliberately cheap: :func:`app.catalog.matcher.product_verdict` reads the
        same file the search itself reads and answers "is this obviously a request
        for catalogue products?".

        It is one-sided on purpose. A query it is unsure about goes to the
        interpreter, which costs one inference and produces a better answer than a
        guess. The opposite error — sending a renovation to a product list because
        the sentence happened to contain a product word — is the expensive one, and
        nothing here can make it: the matcher only ever says yes when the catalogue
        accounts for every meaningful word in the query.
        """
        from app.catalog.matcher import product_verdict
        from app.catalog.store import get_catalog

        return product_verdict(get_catalog(), query)

    async def interpret(self, query: str, session: Session) -> InterpretedIntent:
        if self._interpreter is None:
            from app.core.config import get_settings

            self._interpreter = build_interpreter(get_settings())
        intent = await self._interpreter.interpret(query)
        return self.enrich(intent, session)

    # ------------------------------------------------------------------ #
    def enrich(self, intent: InterpretedIntent, session: Session) -> InterpretedIntent:
        if intent.product_query:
            self._enrich_brand(intent, session)
            self._enrich_category(intent, session)
        if intent.template_slug:
            self._enrich_template(intent, session)
        elif intent.domain is not None:
            # A project template is a database reference, not something the model
            # names: the interpreter reports a domain and a project type, and the
            # template is looked up from those. The model never sees a slug.
            self._enrich_template(intent, session)
        return intent

    # ------------------------------------------------------------------ #
    def _enrich_brand(self, intent: InterpretedIntent, session: Session) -> None:
        """Resolve a brand against the brands the catalogue actually carries."""
        pq = intent.product_query
        if not pq or not pq.raw_brand:
            return
        brand = self._resolve_brand(pq.raw_brand)
        if brand:
            pq.brand_name = brand
            intent.explanations.append(f"برند «{brand}» در کاتالوگ پیدا شد.")
        else:
            intent.explanations.append(
                f"برند «{pq.raw_brand}» در کاتالوگ ثبت نشده است؛ "
                "نتایج بدون فیلتر برند نمایش داده می‌شود."
            )

    def _enrich_category(self, intent: InterpretedIntent, session: Session) -> None:
        """Resolve a category against the catalogue's subcategory slugs."""
        pq = intent.product_query
        if not pq or not pq.category_slug:
            return
        from app.catalog.store import SUBCATEGORY_LABELS, get_catalog

        index = get_catalog()
        slug = pq.category_slug
        if slug not in index.subcategory_slugs():
            # the interpreter may have produced a label rather than a slug
            wanted = normalize_persian(slug)
            for candidate, label in SUBCATEGORY_LABELS.items():
                if normalize_persian(label) == wanted or candidate == wanted:
                    slug = candidate
                    break
        if slug not in index.subcategory_slugs():
            intent.explanations.append(f"دستهٔ «{pq.category_slug}» در کاتالوگ ثبت نشده است.")
            pq.category_slug = None
            pq.category_name = None
            return
        label = index.subcategory_label(slug)
        top = index.top_category_of(slug)
        pq.category_slug = slug
        pq.category_name = label
        if pq.domain is None and top:
            pq.domain = _as_domain(top)
        if intent.domain is None and top:
            intent.domain = _as_domain(top)

    def _enrich_template(self, intent: InterpretedIntent, session: Session) -> None:
        """
        Resolve the project template from the domain and project type.

        The template is an **optional preset** now. A project's requirements come
        from the interpreter, so nothing downstream requires one; this only names
        the rulebook that matches the room and the kind of job, for a project that
        happens to have one, and `ProjectEngine` treats a miss as normal.
        """
        if intent.template_slug is None and intent.domain is None:
            return
        template = None
        if intent.template_slug:
            template = session.scalar(
                select(ProjectTemplate).where(
                    ProjectTemplate.slug == intent.template_slug,
                    ProjectTemplate.is_active.is_(True),
                )
            )
        if template is None and intent.domain:
            template = self._fallback_template(intent.domain, intent.project_type, session)
        if template is None:
            intent.explanations.append("قالب پروژه‌ای برای این نیاز پیدا نشد.")
            intent.template_slug = None
            return
        intent.template_slug = template.slug
        if intent.project_type is None:
            intent.project_type = template.project_type
        if intent.domain is None:
            intent.domain = template.domain

    # ------------------------------------------------------------------ #
    @staticmethod
    def _resolve_brand(raw: str) -> str | None:
        """Match a raw brand string against the catalogue's brand names."""
        from app.catalog.store import get_catalog

        wanted = normalize_persian(raw)
        if not wanted:
            return None
        names = [name for name, _ in get_catalog().brands()]
        for name in names:
            if normalize_persian(name) == wanted:
                return name
        for name in names:
            if wanted and wanted in normalize_persian(name):
                return name
        return None

    @staticmethod
    def _fallback_template(
        domain: Domain, project_type: ProjectType | None, session: Session
    ) -> ProjectTemplate | None:
        stmt = select(ProjectTemplate).where(
            ProjectTemplate.domain == domain, ProjectTemplate.is_active.is_(True)
        )
        if project_type:
            exact = session.scalars(
                stmt.where(ProjectTemplate.project_type == project_type)
            ).first()
            if exact:
                return exact
        return session.scalars(
            stmt.where(ProjectTemplate.project_type == ProjectType.RENOVATION)
        ).first()


def _as_domain(value: str) -> Domain | None:
    return domain_from(value)


def get_search_service() -> SearchService:
    return SearchService()
