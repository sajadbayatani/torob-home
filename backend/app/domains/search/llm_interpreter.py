"""The intent interpreter: a model reading a query, and nothing else.

This is the only thing in the system that decides what a user meant. It is not a
list of phrases: the model is shown the **real catalogue taxonomy** and asked to
map the query onto it, so a room, a job or a product nobody wrote down in this
repository still resolves — as long as the catalogue actually stocks it.

The flow, end to end:

    query
      -> prompt carrying the taxonomy, built from products.json
      -> one chat call
      -> :class:`LLMIntentResponse`, validated (extra keys rejected)
      -> slugs checked against the catalogue *again*
      -> structure only: intent, project facts, search terms

Two properties are load-bearing:

**The model cannot invent a product.** It has no field for one. The worst it can
do is name a slug that is not in the catalogue, and :func:`resolve` moves that
name into ``missing`` instead of using it.

**The model cannot invent a category and have it believed.** Every slug it
returns is looked up in the taxonomy it was given. An unknown slug is dropped
and reported, never searched.

If the LLM is not configured the interpreter fails loudly. There is no
keyword-matching fallback, because a silent fallback is exactly the failure this
replaces: a shop that appears to understand Persian while actually grepping a
word list.
"""

from __future__ import annotations

import logging
import re

from app.core.config import Settings, get_settings
from app.core.enums import Domain, Intent, ProjectType
from app.core.text import normalize_persian
from app.domains.search.interpreter import IntentInterpreter
from app.domains.search.llm_schema import LLMIntentResponse, ProjectIntent
from app.domains.search.schemas import (
    InterpretedIntent,
    ProductQuery,
    RequirementSpec,
)
from app.domains.search.taxonomy import Taxonomy, build_taxonomy

logger = logging.getLogger("home_procurement.search.llm")

SYSTEM_PROMPT = """تو نیت کاربر را تفسیر می‌کنی. قلم مشخصی انتخاب نمی‌کنی، فقط ساختار می‌دهی.

سه intent، و فقط همین سه:
- product_search: دنبال یک یا چند محصول مشخص است. («یه شیر توالت خوب میخوام»)
- project_search: دنبال انجام یک کار در خانه است. («میخوام سرویس بهداشتی رو بازسازی کنم»)
- unknown: نه محصول مشخصی می‌خواهد نه کاری؛ فقط یک محدودیت گفته است. («بودجه‌ام کمه»)

ملاک، انجام یک کار است نه خرید یک قلم؛ عین عبارت‌های کاربر را نشناسای.

قواعد:
- این قاعده فقط دربارهٔ واقعیت‌های پروژه است: room و style را همان‌طور بنویس که
  کاربر گفته، و area_m2 و budget و quality عدد یا مقدار استاندارد آن باشد
  (برای quality نگاشت پایین‌تر آمده). requirements استثناست و قاعدهٔ خودش را
  پایین‌تر دارد.
- اگر عدد یا سلیقه‌ای نگفته، null بگذار.
- room فقط نام اتاق یا فضا باشد، بدون عدد. «اتاق خواب ۱۲متری‌ام» یعنی room=«اتاق خواب» و area_m2=12.
- room عین حرف‌های کاربر است؛ room_token شناسهٔ معتبر اتاق است، از فهرست «شناسه‌های مجاز room_token» نه از فهرست شاهد. نام کاربر را خودت از معنایش به نزدیک‌ترین شناسهٔ آن فهرست برسان؛ null فقط اگر هیچ معنایی نداشت.
- project.type یکی از renovation | new_build | redesign | repair؛ «بسازم» یا «درست کنم» به‌تنهایی new_build نیست، نوع کار را از ماهیتش بفهم.

مهم‌ترین کار تو برای project_search: نوشتن requirements.
دو چیز متفاوت است و قاطی نکن:
- واقعیت‌های پروژه — room و area_m2 و budget و style و goal — فقط همان چیزی است که کاربر گفته.
  quality استثناست: مقدار استانداردش را بنویس، نه لفظ کاربر را.
- requirements — برنامهٔ خریدِ لازم برای رسیدن به نتیجهٔ خواسته‌شده. لازم نیست کاربر آن را نام برده باشد.
  کسی که پروژه‌ای توصیف می‌کند، از تو می‌خواهد بفهمی برای تمام‌کردنش چه باید تهیه شود.
  این برنامه‌ریزی معنایی است، نه حدس‌وگمان و نه ساختن چیز بی‌ربط.
برای هر project_search:
۱. نتیجهٔ خواسته‌شده چیست و دامنه‌اش چقدر است؟
۲. برای رسیدن به آن نتیجه، چه چیزهایی باید تهیه یا انجام شود؟
۳. اگر نتیجه چند جزء روشن دارد، به نیازهای جداگانه بشکن؛ اگر جمله کم گفته، همان‌قدر کلی بمان.
- هر نیاز یک نام عمومی و قابل خرید باشد، مثل اسم قلمی که آدم برای کارش می‌خرد.
  واژهٔ چتری مثل تجهیزات، لوازم، وسایل، فضای یا دکوراسیون نیاز نیست؛ نیاز کلی را به اجزایش بشکن.
- هر نیاز باید به همین پروژه ربط داشته باشد: چیزی که برای رسیدن به نتیجهٔ این کار تهیه می‌شود.
  دامنه را از حرف کاربر بگیر. چیزی که به نتیجهٔ این کار ربطی ندارد ننویس.
- required=true برای اجزای اصلی پروژه و required=false برای اجزای جانبیِ مفید.
- تعداد نیازها را هدف نکن؛ به اندازهٔ دامنهٔ همان پروژه بنویس.
- requirements خالی تقریباً همیشه غلط است؛ فقط وقتی درست است که جمله هیچ پروژه‌ای توصیف نکند.
  جمله‌ای که یک کار در خانه توصیف می‌کند، نیاز دارد؛ حتی اگر کاربر هیچ اسمی نبرده باشد.
- موجود بودن در کاتالوگ ملاک نیست؛ بعداً مشخص می‌شود کدام نیاز محصول دارد. نیازِ بی‌محصول هم نیازِ درست است.
- description کوتاه باشد و نیاز را از نظر کاربرد بگوید.
- terms فقط همان نام کوتاه و قابل خرید، برای تطبیق با کاتالوگ؛ نه جملهٔ کاربر و نه عبارت بلند.
- quantity فقط اگر کاربر گفته؛ وگرنه null. quality_min هم فقط اگر گفته، و آن هم با نگاشت کیفیت.
- در requirements نام برند، مدل، فروشنده، قیمت، مشخصهٔ فنی یا شناسهٔ کاتالوگ ننویس؛
  نام دستهٔ کالا را بنویس، ولی قلم مشخصی را انتخاب نکن.
- category یکی از دسته‌هایی است که به تو داده‌ام، یا null.
- برای product_search، terms فقط کلمه‌های اصلی محصول باشد؛ «یه»، «میخوام»، «خوب» را ننویس.
- budget عدد تومان است: «۵۵ میلیون» یعنی 55000000.

کیفیت: در constraints.quality و requirements[].quality_min فقط یکی از این چهار مقدار
بنویس، هرچه لفظ کاربر بوده چه:
  low    = اقتصادی | معمولی | پایه | ارزان
  medium = متوسط | متوسط رو به بالا
  high   = خوب | باکیفیت | مرغوب
  ultra  = لوکس | بسیار باکیفیت | پریمیوم | حرفه‌ای
هر لفظ دیگری به نزدیک‌ترین همین چهار برود. «لوکس» یعنی ultra، نه خودِ «لوکس».
اگر کاربر کیفیت نگفته، null. لفظ اصلی کاربر را فقط در explanations فارسی بیاور.
- در search نام برند، فروشنده یا قیمت ننویس.
- explanations حداکثر ۲ مورد، کوتاه و فارسی.

ساختار را دقیق نگه دار: هر فیلد در جای خودش، نه یک لایه داخل‌تر.
این خروجی فقط یک لایهٔ ریشه دارد و project تنها شیء تودرتوی آن است.
در project فقط این کلیدها مجاز است: type، room، room_token، area_m2، goal، constraints، requirements.
هرگز search را داخل project ننویس؛ search یا null است یا شیء‌ای در ریشه.
هرگز شیء constraints ریشه، constraint_kind، confidence یا explanations را داخل project ننویس؛
این‌ها همگی در ریشه می‌نشینند، کنار project و نه درون آن.
دو فیلد constraints کاملاً متفاوت‌اند و هرگز یکی نشوند و جابه‌جا نشوند:
- project.constraints فهرست است، درون project. فقط محدودیت‌هایی که کاربر برای خودِ کار گفته.
- constraints شیء است، در ریشه. کیفیت و بودجه و یادداشت‌های محدودیت خرید اینجاست.
یکی را در جای دیگری ننویس؛ کیفیت و بودجه در constraints ریشه‌اند، نه در project.

همین حالا JSON را بنویس.
تحلیل، استدلال، برنامه‌ریزی یا یادداشت ننویس.
هیچ reasoning یا prose تولید نکن.
فقط و فقط یک JSON object مطابق schema برگردان.
پیش از JSON و پس از آن هیچ متنی ننویس و markdown نگذار.
تنها prose مجاز، همان explanations کوتاه فارسی است که خودش یک فیلد JSON است.

فقط و فقط یک JSON object بده، بدون markdown و بدون هیچ متنی بیرون از آن:
{"intent":"...","category":null,"project":{"type":null,"room":null,"room_token":null,"area_m2":null,"goal":null,"constraints":[],"requirements":[{"description":"...","terms":["..."],"quantity":null,"required":true,"quality_min":null}]},"search":null,"constraints":{"quality":null,"budget":null,"notes":[]},"constraint_kind":"NONE","confidence":0.0,"explanations":[]}"""


def _is_latin(word: str) -> bool:
    """Whether a word is a model code rather than a name.

    Latin letters, or no letters at all: "5050" and "32xh605" are product codes,
    and neither can be the name of a space.
    """
    letters = [ch for ch in word if ch.isalpha()]
    return not letters or all(ch.isascii() for ch in letters)


class LLMInterpreter:
    """Reads a query with a model that has been shown the catalogue."""

    name = "llm"

    def __init__(self, settings: Settings | None = None, taxonomy: Taxonomy | None = None) -> None:
        self._settings = settings or get_settings()
        self._taxonomy = taxonomy

    # ------------------------------------------------------------------ #
    def taxonomy(self) -> Taxonomy:
        """Built once per interpreter, from the catalogue as it is now."""
        if self._taxonomy is None:
            self._taxonomy = build_taxonomy(
                max_brands=self._settings.intent_taxonomy_max_brands
            )
        return self._taxonomy

    async def interpret(self, query: str) -> InterpretedIntent:
        # fail by name, rather than degrading into something that looks like it works
        self._settings.require_llm()

        taxonomy = self.taxonomy()
        user_prompt = self._user_prompt(query, taxonomy)
        payload = self._call(system=SYSTEM_PROMPT, user=user_prompt)
        response = LLMIntentResponse.model_validate(payload)
        return self.resolve(query, response, taxonomy)

    def _user_prompt(self, query: str, taxonomy: Taxonomy) -> str:
        """
        The query, and the four category names. Nothing else.

        This used to carry 22 subcategory slugs and 35 brand names as well. The
        model then answered `subcategories: ["furniture"]` — a category, where a
        subcategory was asked for — because it had been given both vocabularies
        and no way to tell them apart. It no longer names subcategories at all,
        so it no longer needs to be shown them.
        """
        # The canonical identifiers and the evidence that identifies them are two
        # different things, and the model needs them apart. Presenting the
        # evidence *as* the list made the tokens unreadable: the same words appear
        # under several rooms, so there was nothing to choose between.
        tokens = " | ".join(token for token, _words in taxonomy.rooms)
        # The words that name a space are its Persian ones; the rest are model
        # codes that happen to sit in the same products. Sorted alphabetically the
        # codes came first and crowded out the only words that carry meaning, so
        # the ones that describe the room lead.
        # A word that appears in one room only is what identifies that room; a
        # word every room shares is a brand or a model code and says nothing.
        # Ranking by how many rooms use a word is arithmetic over the file, and it
        # is what puts مبل under living_room instead of a list of model numbers.
        spread: dict[str, int] = {}
        for _token, words in taxonomy.rooms:
            for word in words:
                spread[word] = spread.get(word, 0) + 1

        def _evidence_words(words: tuple[str, ...]) -> str:
            named = [w for w in words if not _is_latin(w)]
            named.sort(key=lambda w: (spread.get(w, 0), w))
            return "، ".join(named[:6])

        evidence = "\n".join(
            f"- {token}: {_evidence_words(words)}" for token, words in taxonomy.rooms
        )
        return (
            f"دسته‌های کاتالوگ: {taxonomy.render_categories()}\n"
            f"\nشناسه‌های مجاز room_token:\n{tokens}\n"
            f"\nشاهد برای شناخت اتاق (نه شناسه):\n{evidence}\n"
            f"\nپرسش کاربر:\n{query}"
        )

    def _call(self, *, system: str, user: str) -> dict:
        """
        Ask **the configured model**, and give it more room if it thought too long.

        The model is never chosen here, and never changes: the client resolves it
        from settings once and reuses it for every attempt, including a retry with
        a larger budget. A reasoning model that runs out of tokens mid-thought
        replies with no answer at all, which is a sizing problem rather than an
        outage, so the client retries it on the same model before anyone is told
        the LLM is unavailable.
        """
        from app.core.config import get_settings
        from app.llm import chat_json

        settings = get_settings()
        return chat_json(
            system=system,
            user=user,
            # the schema is a request; LLMIntentResponse remains the authority
            schema_model=LLMIntentResponse,
            # The only call that asks for a reasoning effort. This task is a small
            # structured judgement — read a sentence, classify it, name a room — and
            # a reasoning model that thinks at length about it spends the whole
            # token budget before answering, which is what the truncation retry
            # exists to paper over. Asking for less thinking makes the first attempt
            # the answer. `max_tokens` is untouched: the budget is the operator's
            # to set, and this only changes how much of it gets used.
            reasoning_effort=settings.llm_reasoning_effort,
        )

    # ------------------------------------------------------------------ #
    def resolve(
        self, query: str, response: LLMIntentResponse, taxonomy: Taxonomy
    ) -> InterpretedIntent:
        """
        Turn the validated model answer into the system's own intent.

        The model contributed semantics. Everything else is decided here:

        * ``category`` is checked against the categories the catalogue actually
          has. One it does not have is dropped, not coerced.
        * the subcategories a product query maps to are detected from the
          catalogue's own labels, not taken from the model — so a slug can only
          ever be a slug the catalogue contains.
        * a "project" with no category behind it is downgraded to unknown rather
          than turned into a basket of nothing.
        """
        explanations = list(response.explanations)
        if response.category_raw and response.category is None:
            explanations.append(
                f"دستهٔ «{response.category_raw}» در کاتالوگ ما نیست و نادیده گرفته شد."
            )
        category = self._valid_category(response.category, taxonomy, explanations)

        if response.intent == "project_search" and category is None:
            # The model said this person wants work done, and that judgement is
            # the one thing here that cannot be derived from the catalogue. A
            # category we could not resolve is a *reference* we failed to place —
            # it is not a reason to doubt the intent. Downgrading to UNKNOWN used
            # to do exactly that, and UNKNOWN is defined to fall back to the
            # catalogue, so «بازسازی آشپزخانه ۱۰ متری» lost its project status and
            # was answered with kitchen products instead. The intent therefore
            # stays a project, carrying the room and area the model did give; if
            # no domain can be reached from them the project flow says so itself,
            # which is a truer answer than a list of unrelated products.
            intent_kind = Intent.NEED_SEARCH
            explanations.append(
                "دستهٔ این پروژه در کاتالوگ ما پیدا نشد؛ اتاق و متراژی که گفتید "
                "همچنان مبنای پروژه است."
            )
        else:
            intent_kind = self._as_intent(response.intent)

        product_query = None
        matched: list[str] = []
        if intent_kind is Intent.PRODUCT_SEARCH:
            # deterministic: the catalogue matches its own labels against the text
            matched, product_query = self._product_query(
                query, response, category, taxonomy
            )

        project = response.project
        requirements = RequirementSpec(
            area_m2=project.area_m2 if project else None,
            quality=response.constraints.quality,
            budget=response.constraints.budget,
            priorities=[],
        )

        return InterpretedIntent(
            intent=intent_kind,
            domain=category,
            project_type=project.type if project else None,
            product_query=product_query,
            requirements=requirements,
            constraint_kind=response.constraint_kind_from_evidence(),
            confidence=response.confidence,
            interpreter=self.name,
            explanations=explanations,
            matched_subcategories=matched,
            # which subcategories a *project* needs is the backend's decision,
            # resolved in the project engine; the model does not propose them
            missing_categories=[],
            #: The project's requirements, in the model's own understanding. This
            #: is the whole point of the interpreter: *what this person is trying
            #: to achieve* is understanding, and a predefined rulebook cannot do
            #: it. What it cannot do is name a catalogue product, so it says what
            #: is needed in words and the project engine resolves those words
            #: against the file.
            project_requirements=list(project.requirements) if project else [],
            room=self._clean_room(project.room if project else None),
            #: the catalogue room this project is about, when we could place it.
            #: Checked against the rooms the catalogue actually carries, so the
            #: model can name a space but cannot invent one.
            room_token=self._room_token(response, taxonomy, project),
            goal=project.goal if project else None,
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _room_token(
        response: LLMIntentResponse, taxonomy: Taxonomy, project: ProjectIntent | None
    ) -> str | None:
        """
        Which of the catalogue's rooms this project is about.

        The model's answer is used only when it names a room the catalogue
        really has, or when the user's own word matches one of its words
        deterministically. Users write "پذیرایی" where the file says
        "living_room" and no amount of string matching closes that gap, so the
        model is asked; the catalogue still decides whether the answer counts.

        Returns None for a space the catalogue does not carry, which is a
        different thing from a project being invalid.
        """
        if project is None:
            return None
        known = {token for token, _words in taxonomy.rooms}
        claimed = (project.room_token or "").strip()
        if claimed and claimed in known:
            return claimed
        # the user's own words, matched against the same vocabulary
        if project.room:
            found = taxonomy.room_token(project.room)
            if found:
                return found
        return None

    # ------------------------------------------------------------------ #
    @staticmethod
    def _clean_room(room: str | None) -> str | None:
        """
        The room name, without a measurement left in it.

        A small model tends to put "۱۲متری‌ام" in the room field, which then reads
        as the room's name everywhere it is shown. The area belongs in
        ``area_m2``; if the whole value is a measurement there is no room named
        at all, so it is dropped rather than displayed.
        """
        if not room:
            return None
        # longest alternative first, or "متر" eats the start of "متری" and
        # leaves a stray letter behind
        cleaned = room
        cleaned = re.sub(r"(مترمربع|متر مربع|متری|متر|سانتیمتر|سانتی|درصد)", " ", cleaned)
        cleaned = re.sub(r"[\d\u06f0-\u06f9\u0660-\u0669]+", " ", cleaned)
        # ZWNJ is dropped for the measurement match, but restored so a word like
        # "آشپزخونه‌م" is not silently glued into "آشپزخونهم"
        cleaned = re.sub(r"\s*\u200c\s*", "\u200c", cleaned)
        # ZWNJ is allowed through: it is part of Persian orthography, not punctuation
        cleaned = re.sub(r"[^\w\u0600-\u06ff\u200c\s]", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ،.-")
        # a leftover joiner carries no meaning once the words around it are gone
        cleaned = cleaned.strip("\u200c ")
        if not cleaned:
            return None
        # what is left of "۱۲متری‌ام" is "ام": a possessive ending, not a room
        if len(cleaned) <= 2:
            return None
        # A possessive ending is left alone on purpose. Persian suffixes are not
        # separable without morphology — "مبلمان" ends in "مان" too — and quietly
        # mangling the user's words is worse than storing "اتاق خوابم" verbatim.
        return cleaned

    @staticmethod
    def _valid_category(
        claimed: Domain | None, taxonomy: Taxonomy, explanations: list[str]
    ) -> Domain | None:
        """Keep the category only if the catalogue really has it."""
        if claimed is None:
            return None
        if not taxonomy.has_category(claimed.value):
            explanations.append(
                f"دستهٔ «{claimed.value}» در کاتالوگ ما نیست و نادیده گرفته شد."
            )
            return None
        return claimed

    def _product_query(
        self, query: str, response: LLMIntentResponse, domain: Domain | None, taxonomy: Taxonomy
    ) -> tuple[list[str], ProductQuery]:
        """
        Build the product query, and detect its subcategory from the catalogue.

        The slug comes from :func:`app.catalog.store.detect_category`, which
        matches the query against the catalogue's own Persian labels. The model
        names the words; the catalogue decides what they mean.
        """
        from app.catalog.store import detect_category, get_catalog

        text = response.text_for_search(query)
        detected = detect_category(get_catalog(), text)
        # A tie between subcategories is not a reading, so it is not used as one.
        # The model's own `category` is left to say what it meant.
        slug = detected.slug if detected and detected.decisive else None
        if slug is None and domain is not None:
            # the model placed the query in a category we do stock
            slug = None
        label = taxonomy.label_of(slug) if slug else None
        search = response.search
        raw_brand = self._match_brand(search.brand, taxonomy) if search else None
        if raw_brand is None and search and search.brand:
            raw_brand = search.brand
        return (
            [slug] if slug else [],
            ProductQuery(
                text=text,
                tokens=text.split(),
                raw_brand=raw_brand,
                category_slug=slug,
                category_name=label,
                domain=domain,
                quality=response.constraints.quality,
                style=None,
            ),
        )

    # ------------------------------------------------------------------ #
    @staticmethod
    def _as_intent(value: str) -> Intent:
        return {
            "product_search": Intent.PRODUCT_SEARCH,
            "project_search": Intent.NEED_SEARCH,
        }.get(value, Intent.UNKNOWN)

    @staticmethod
    def _match_brand(raw: str, taxonomy: Taxonomy) -> str | None:
        """Resolve a brand the model named to one the catalogue carries."""
        wanted = normalize_persian(raw)
        if not wanted:
            return None
        for name in taxonomy.brands:
            if normalize_persian(name) == wanted:
                return name
        for name in taxonomy.brands:
            if wanted in normalize_persian(name):
                return name
        return None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        key = value.strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


#: kept for callers that used the old factory
build_llm_interpreter = LLMInterpreter

__all__ = ["LLMInterpreter", "SYSTEM_PROMPT", "build_llm_interpreter", "IntentInterpreter"]
