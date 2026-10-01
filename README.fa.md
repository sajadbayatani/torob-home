# ترب خونه --- دستیار تأمین خرید برای پروژه‌های خانه

> یک دستیار تأمین خرید مبتنی بر intent که هدف کاربر در خانه را به
> نیازهای قابل تأمین، محصولات واقعی کاتالوگ، لیست انتخاب‌ها و اطلاعات
> قیمت و فروشنده تبدیل می‌کند.

## ۱. معرفی

«ترب خونه» یک prototype برای دستیار تأمین خرید در حوزه خانه است. مسئله
صرفاً جست‌وجوی محصول یا مقایسه قیمت نیست.

در جست‌وجوی معمولی، کاربر محصول را می‌گوید:

``` text
ماشین لباسشویی
       ↓
محصولات → فروشنده‌ها → قیمت‌ها
```

اما جریان اصلی پروژه از هدف کاربر شروع می‌شود:

``` text
بازسازی سرویس بهداشتی ۱۲ متری
       ↓
intent
       ↓
نیازهای پروژه
       ↓
زیرگروه‌های کاتالوگ
       ↓
محصولات واجد شرایط
       ↓
لیست انتخاب‌ها
       ↓
بودجه / فروشنده / بهینه‌سازی
```

اصل اصلی محصول این است:

> سیستم باید بفهمد کاربر در خانه می‌خواهد چه کاری انجام دهد، این هدف را
> به نیازهای قابل تأمین تبدیل کند و سپس آن نیازها را از یک کاتالوگ
> کنترل‌شده از محصولات واقعی تأمین کند.

LLM برای تفسیر معنایی و reasoning محدود استفاده می‌شود؛ اما منبع حقیقت
برای محصول، قیمت، فروشنده، موجودی و محاسبات مالی نیست.

این repository یک prototype/demo است و یک marketplace production-ready
نیست.

------------------------------------------------------------------------

## ۲. دامنه محصول

در حال حاضر دو intent اصلی داریم.

### ۲.۱ جست‌وجوی محصول

کاربر تقریباً می‌داند چه چیزی می‌خواهد بخرد:

``` text
یه شیر توالت خوب میخوام
سینک ظرفشویی
دنبال یه ماشین لباسشویی تا ۳۰ تومن میگردم
```

سیستم باید محصول را از کاتالوگ پیدا کند، محدودیت‌های صریح را اعمال کند و
در صورت وجود، offerها و فروشنده‌ها را نمایش دهد.

اگر query از ابتدا به‌اندازه کافی واضح باشد که یک جست‌وجوی مستقیم محصول
محسوب شود، نباید برای آن LLM صدا زده شود.

### ۲.۲ جست‌وجوی پروژه / نیاز

کاربر به جای اسم محصول، یک کار، فضا یا نتیجه را توصیف می‌کند:

``` text
بازسازی سرویس بهداشتی ۱۲ متری
اتاق خواب ۱۲ متری رو می‌خوام تغییر دکوراسیون بدم
برای آشپزخونه ۱۰ متری چی لازم دارم؟
```

سیستم ساختار پروژه را استخراج می‌کند و نیازهای خرید را از دل آن توصیف
درمی‌آورد.

Requirement یک محصول نیست؛ بیان می‌کند برای رسیدن به هدف پروژه چه چیزی
لازم است.

### ۲.۳ لیست انتخاب‌ها

مفهوم سبد خرید در این پروژه «لیست انتخاب‌ها» است.

این لیست نشان‌دهنده محصولاتی است که کاربر صراحتاً برای مقایسه، بررسی یا
برنامه‌ریزی انتخاب کرده است.

لیست انتخاب‌ها:

-   checkout نیست؛
-   سیستم پرداخت نیست؛
-   quantity محصول ندارد؛
-   محل ورود خودکار recommendation نیست.

افزودن و حذف محصول صریح است. عملیات گروهی نیز روی product IDهای واقعی
مجموعه فعلی پروژه انجام می‌شود.

quantity مربوط به requirement پروژه با quantity محصول متفاوت است و
همچنان معتبر است.

------------------------------------------------------------------------

## ۳. اصول اصلی محصول

### ۳.۱ اول intent، بعد حقیقت کاتالوگ

لایه معنایی مشخص می‌کند:

-   کاربر چه چیزی گفته است؟
-   query محصول است یا پروژه؟
-   اتاق یا زمینه پروژه چیست؟
-   چه requirementهایی از هدف بیان‌شده حاصل می‌شود؟
-   چه محدودیت‌هایی صریحاً گفته شده‌اند؟

کاتالوگ مشخص می‌کند:

-   چه محصولاتی وجود دارند؛
-   هر محصول در چه subcategoryای است؛
-   برای چه اتاق‌ها و use caseهایی مناسب است؛
-   چه offer و فروشنده‌ای دارد؛
-   قیمت چیست؛
-   چه محصولاتی مکمل یا جایگزین هستند.

این دو مسئولیت نباید با هم مخلوط شوند.

### ۳.۲ LLM اجازه ساختن اطلاعات کاتالوگ را ندارد

Schema مربوط به interpretation هیچ فیلدی برای product، seller، offer یا
price ندارد.

LLM می‌تواند تولید کند:

``` text
intent
project type
room
area
goal
requirements
search terms
quality/budget constraints
```

اما product record مرجع تولید نمی‌کند.

در reasoning پروژه نیز LLM فقط candidateهای محدودی را می‌بیند که backend
از کاتالوگ تولید کرده است.

مدل نمی‌تواند دامنه candidateها را گسترش دهد.

### ۳.۳ محدودیت‌های سخت با کد اعمال می‌شوند

Backend مالک حقیقت این موارد است:

-   وجود محصول در کاتالوگ؛
-   category/subcategory؛
-   room eligibility؛
-   project applicability؛
-   محدودیت بودجه؛
-   product ID؛
-   قیمت؛
-   offer فروشنده؛
-   وضعیت لیست انتخاب‌ها؛
-   candidate generation.

LLM نباید مسئول enforcement این موارد باشد.

### ۳.۴ هیچ تغییر بی‌اجازه‌ای انجام نمی‌شود

Reasoning می‌تواند replacement یا optimization پیشنهاد کند، اما انتخاب
صریح کاربر را بی‌اجازه تغییر نمی‌دهد.

تغییر selection فقط بعد از تأیید کاربر اعمال می‌شود.

Recommendation نیز خودکار وارد لیست انتخاب‌ها نمی‌شود.

------------------------------------------------------------------------

## ۴. مسیریابی query

ورودی جست‌وجو ابتدا از یک product matcher قطعی عبور می‌کند:

``` text
Search query
    │
    ▼
Deterministic product matcher
    │
    ├── محصول واضح
    │      ↓
    │   Product Search
    │   بدون LLM
    │
    └── محصول واضح نیست
           ↓
       LLM interpretation
           │
           ├── product_search
           ├── project_search
           └── unknown
```

matcher قرار نیست تمام زبان طبیعی را بفهمد.

فقط باید با confidence کافی ثابت کند که query یک جست‌وجوی مستقیم محصول
است.

False negative قابل قبول است؛ query مبهم می‌تواند به interpretation برود.

False positive خطرناک‌تر است، چون interpretation را دور می‌زند.

برای این routing از مدل دوم، embedding، سرویس semantic خارجی یا phrase
map مخصوص queryهای فارسی استفاده نمی‌شود.

------------------------------------------------------------------------

## ۵. معماری Interpretation

برای queryهایی که product-first نیستند، یک interpretation call انجام
می‌شود.

ساختار مفهومی خروجی:

``` json
{
  "intent": "project_search",
  "category": null,
  "project": {
    "type": "renovation",
    "room": "سرویس بهداشتی",
    "room_token": "bathroom",
    "area_m2": 12,
    "goal": "بازسازی سرویس بهداشتی",
    "constraints": [],
    "requirements": []
  },
  "search": null,
  "constraints": {
    "quality": "medium",
    "budget": null,
    "notes": []
  },
  "constraint_kind": "QUALITY",
  "confidence": 0.99,
  "explanations": []
}
```

Schema با Pydantic و JSON Schema enforce می‌شود.

Intentها:

-   `product_search`
-   `project_search`
-   `unknown`

لایه interpretation باید اطلاعاتی را که کاربر نگفته است اختراع نکند.

Requirementها استثنای آگاهانه‌اند؛ چون برای project search باید نیازهای
خرید از هدف پروژه به‌صورت معنایی استخراج شوند.

### ۵.۱ نرمال‌سازی کیفیت

عبارت‌های فارسی به enum استاندارد تبدیل می‌شوند:

  عبارت کاربر                      مقدار canonical
  -------------------------------- -----------------
  اقتصادی / معمولی / پایه          `low`
  متوسط                            `medium`
  خوب / باکیفیت                    `high`
  لوکس / بسیار باکیفیت / پریمیوم   `ultra`

Schema API مقدار canonical را نگه می‌دارد.

### ۵.۲ خروجی ساختاری سخت‌گیرانه

LLM با JSON Schema فراخوانی و سپس با Pydantic validate می‌شود.

مدل‌ها `extra="forbid"` دارند.

بنابراین JSONای که از نظر معنایی درست ولی از نظر ساختار اشتباه باشد،
معتبر محسوب نمی‌شود.

این رفتار عمدی است؛ چون downstream نباید روی ساختار نامطمئن کار کند.

ساختار root در prompt صراحتاً تعریف شده است؛ این کار بعد از یک regression
مهم لازم شد که مدل فیلدهای root مانند `search`، `constraints`،
`confidence` و `explanations` را اشتباهاً داخل `project` قرار می‌داد.

------------------------------------------------------------------------

## ۶. مدل Requirement

Requirement یک نیاز معنایی برای پروژه است، نه یک محصول کاتالوگ.

نمونه:

``` json
{
  "description": "شیرهای سرویس بهداشتی",
  "terms": ["شیر", "توالت"],
  "quantity": 1,
  "required": true,
  "quality_min": "medium"
}
```

Requirement نباید شامل این موارد باشد:

-   product ID؛
-   seller؛
-   model؛
-   price؛
-   catalogue-specific product information.

Requirement باید حتی در صورت نبود محصول مناسب در کاتالوگ همچنان معتبر
بماند.

اگر برای requirement محصولی وجود نداشته باشد، آن requirement به‌عنوان
unmet نمایش داده می‌شود و حذف یا با محصول نامرتبط جایگزین نمی‌شود.

### ۶.۱ quantity requirement در برابر quantity محصول

این تفکیک مهم است.

`requirement.quantity` می‌گوید:

> چه مقدار از این نیاز پروژه لازم است؟

نه اینکه:

> چند عدد از این محصول خاص باید خریداری شود؟

quantity محصول در مدل فعلی محصول/لیست انتخاب‌ها وجود ندارد.

------------------------------------------------------------------------

## ۷. کاتالوگ

کاتالوگ منبع حقیقت محصولات است.

کاتالوگ canonical فعلی شامل ۷۰ محصول انتخاب‌شده در چهار domain است:

-   bathroom
-   kitchen
-   furniture
-   appliances

هر محصول یک‌بار به‌صورت offline enrich شده است.

Metadata شامل مواردی مانند:

``` text
rooms
product_roles
use_cases
project_types
space_fit
styles
features
search_terms
complementary_subcategories
alternative_subcategories
```

این enrichment در runtime انجام نمی‌شود.

### ۷.۱ چرا enrichment داریم؟

نام خام محصول برای فهم پروژه کافی نیست.

مثلاً یک تخت می‌تواند همزمان مفهوم‌های زیر را داشته باشد:

-   sleeping؛
-   bedroom؛
-   storage؛
-   small-space use؛
-   project-specific relevance.

این semantics یک‌بار در canonical catalogue ثبت می‌شود، نه اینکه در هر
query دوباره با LLM کشف شود.

### ۷.۲ abstraction منبع محصول

دسترسی به product source از business logic جدا شده است:

``` text
ProductSource
├── LocalJsonProductSource
└── TorobMcpProductSource
```

تنظیم منبع از `.env` انجام می‌شود:

``` env
PRODUCT_SOURCE=local
TOROB_MCP_URL=https://torob-mcp.sajjadbayatani.workers.dev/mcp
```

یا:

``` env
PRODUCT_SOURCE=torob_mcp
```

source فقط وظیفه تأمین داده کاتالوگ را دارد و مسئول این موارد نیست:

-   intent interpretation؛
-   requirement generation؛
-   ranking؛
-   project reasoning؛
-   optimization.

------------------------------------------------------------------------

## ۸. Requirement به Subcategory

این بخش deterministic است.

Requirement چند term کوتاه دارد و backend آن‌ها را به subcategoryهای
کاتالوگ resolve می‌کند.

Substring matching عمداً کنار گذاشته شد؛ چون خطاهایی مانند این ایجاد
می‌کرد:

``` text
مبل → مبلمان
```

و بعضی عبارت‌های مرتبط را از دست می‌داد:

``` text
میز تحریر ↔ میز کار
```

matcher با vocabulary استخراج‌شده از خود کاتالوگ کار می‌کند.

یک term فقط وقتی evidence محسوب می‌شود که:

1.  کاتالوگ آن را به‌عنوان vocabulary معتبر یک subcategory ارائه کرده
    باشد؛
2.  آن term بین تعداد زیادی subcategory مشترک نباشد.

بنابراین کلمات عمومی که در بسیاری از subcategoryها وجود دارند، نمی‌توانند
به‌تنهایی یک محصول خاص را برنده کنند.

### ۸.۱ کلمات اتاق evidence محصول نیستند

این یک regression واقعی بود و اکنون یک invariant صریح است.

مثلاً:

``` text
آینه سرویس بهداشتی
```

شامل `سرویس` و `بهداشتی` است.

این دو کلمه نباید باعث شوند requirement به mirror تبدیل شود.

Room قبلاً از طریق `RoomScope` اعمال می‌شود.

پس معماری درست:

``` text
room → RoomScope
requirement terms → product evidence
```

است، نه:

``` text
room + requirement terms → product evidence
```

به همین دلیل کلمات room قبل از scoring حذف می‌شوند.

این اصلاح جلوی حالتی را می‌گیرد که چون `آینه سرویس بهداشتی` تنها label
دارای نام کامل room بود، requirementهای plumbing یا lighting نیز به
`bathroom-mirror` resolve شوند.

------------------------------------------------------------------------

## ۹. Candidate Generation

بعد از resolution زیرگروه‌ها، backend candidateها را تولید می‌کند.

فیلترهای سخت deterministic شامل مواردی مانند:

-   room پروژه؛
-   product role؛
-   project type؛
-   space fit؛
-   quality در صورت وجود داده قابل اتکا؛
-   budget؛
-   وجود واقعی محصول در catalogue؛
-   قابلیت خرید/عرضه.

LLM کل کاتالوگ را دریافت نمی‌کند.

فقط candidateهای محدود و مرتبط را دریافت می‌کند.

### ۹.۱ بودجه

Budget در صورت اعلام، محدودیت سخت است.

مثلاً:

``` text
دنبال یه ماشین لباسشویی تا ۳۰ تومن میگردم
```

نباید محصولی با قیمت بالاتر از ۳۰ میلیون را صرفاً به‌دلیل شباهت متنی
برگرداند.

Structured constraints باید بر token matching عمومی غالب باشند.

محاسبات پولی در backend و با مقدار integer Toman انجام می‌شود.

------------------------------------------------------------------------

## ۱۰. محصولات مکمل

رابطه مکمل از خود کاتالوگ می‌آید.

LLM نباید آن را اختراع کند.

محصول مکمل باید:

-   رابطه مکمل تعریف‌شده در کاتالوگ داشته باشد؛
-   subcategory متفاوتی داشته باشد؛
-   فیلترهای room/project را پاس کند.

Alternative با complement یکی نیست:

``` text
same subcategory → alternative
different declared complementary subcategory → complement
```

در حال حاضر اگر یک requirement به چند subcategory resolve شود، ممکن است
complementها برای چند slug ساخته شوند. این یک موضوع مستقل برای بهینه‌سازی
candidate generation است و نباید با منطق اصلی matching قاطی شود.

------------------------------------------------------------------------

## ۱۱. Project Reasoning

LLM فقط بعد از deterministic candidate generation وارد می‌شود:

``` text
project
  +
requirements
  +
bounded candidates
  +
constraints
  ↓
reasoning model
  ↓
structured proposal
  ↓
backend validation
  ↓
final selections
```

مدل می‌تواند:

-   بین candidateها انتخاب کند؛
-   دلیل انتخاب را توضیح دهد؛
-   trade-offها را مقایسه کند؛
-   تحت بودجه یا constraint جدید جایگزین پیشنهاد دهد.

مدل نمی‌تواند:

-   product ID بسازد؛
-   seller بسازد؛
-   price بسازد؛
-   candidate جدید اختراع کند؛
-   constraint سخت را نقض کند؛
-   selection کاربر را بی‌اجازه تغییر دهد.

### ۱۱.۱ یک reasoning call برای هر تصمیم

اول deterministic logic تمام کارهایی را که قطعی هستند انجام می‌دهد.

اگر یک requirement فقط یک candidate معتبر داشته باشد، نیازی به LLM برای
انتخاب وجود ندارد.

اگر انتخاب واقعی وجود داشته باشد، یک reasoning call محدود انجام می‌شود.

این کار هم latency و هم هزینه LLM را کنترل می‌کند.

------------------------------------------------------------------------

## ۱۲. Recalculation و Optimization

سه حالت جدا داریم.

### Query جدید

``` text
query
 → interpretation
 → deterministic requirement/candidate generation
 → reasoning
```

در حالت نیازمند reasoning:

``` text
1 interpretation call
1 reasoning call
```

### تغییر constraint در همان پروژه

اگر area، quality، budget یا constraint پروژه تغییر کند، interpretation
قبلی قابل reuse است:

``` text
existing interpretation
 → deterministic recalculation
 → reasoning
```

نباید همان query دوباره تفسیر شود.

### بهینه‌سازی لیست انتخاب‌ها

Optimization روی project context موجود و selection list فعلی انجام
می‌شود.

query اصلی دوباره به interpretation فرستاده نمی‌شود.

``` text
existing project
+
current selection
+
new optimization constraints
 → deterministic candidates
 → one optimization reasoning call
 → proposal
 → user confirmation
```

Optimization یک search جدید نیست.

یک تصمیم محدود روی state موجود پروژه و selection است.

هیچ replacementای بدون تأیید کاربر اعمال نمی‌شود.

------------------------------------------------------------------------

## ۱۳. Semantics لیست انتخاب‌ها

لیست انتخاب‌ها بر اساس product ID است و idempotent رفتار می‌کند.

ویژگی‌ها:

-   افزودن دوباره همان محصول duplicate ایجاد نمی‌کند؛
-   حذف محصول explicit است؛
-   package selection روی product IDهای واقعی recommendation فعلی کار
    می‌کند؛
-   partial selection ممکن است؛
-   فقط محصولاتی که واقعاً در catalogue match شده‌اند قابل انتخاب‌اند؛
-   requirementهای پروژه مستقل از selection state هستند؛
-   optimization پیشنهاد می‌دهد و بی‌اجازه mutation نمی‌کند.

عبارت‌های UI:

-   افزودن به لیست انتخاب‌ها
-   حذف از لیست انتخاب‌ها
-   در لیست انتخاب‌ها
-   لیست انتخاب‌های من
-   بهینه‌سازی انتخاب‌ها

------------------------------------------------------------------------

## ۱۴. Product Detail

صفحه محصول روی خود محصول و اطلاعات تأمین آن تمرکز دارد:

-   مشخصات محصول؛
-   category/subcategory؛
-   اطلاعات تصویری؛
-   attributes؛
-   قیمت؛
-   seller offers؛
-   محصولات مشابه.

«محصولات مشابه» جایگزین‌های همان context محصول هستند.

Complementary products لازم نیست در صفحه detail به‌عنوان یک بخش مستقل
نمایش داده شوند، اما metadata مربوط به مکمل‌ها همچنان برای project
reasoning و optimization استفاده می‌شود.

------------------------------------------------------------------------

## ۱۵. معماری API و Backend

Backend یک modular monolith با FastAPI است:

``` text
domains/
├── catalog/
├── sellers/
├── search/
├── projects/
└── basket/
```

و زیرساخت:

``` text
app/
├── core/
├── db/
├── catalog/
├── llm/
└── seed/
```

`app/catalog` عمداً زیر `domains` نیست.

این بخش data/catalog layer است و مسئول:

-   index؛
-   matching؛
-   product source؛
-   selection logic؛
-   projections؛
-   complementary relationships.

Domainهای HTTP orchestration و API response را مدیریت می‌کنند.

------------------------------------------------------------------------

## ۱۶. نقش PostgreSQL

PostgreSQL محل state متعلق به application است.

کاتالوگ لازم نیست به جدول product تبدیل شود؛ چون در این prototype یک
dataset versioned و قابل review است.

کاتالوگ:

-   قابل diff است؛
-   قابل بررسی است؛
-   reproducible است؛
-   به‌راحتی قابل تعویض است.

Database برای stateهای application مانند:

-   project/analysis؛
-   selection list؛
-   selection items؛
-   سایر stateهای persistent پروژه

استفاده می‌شود.

------------------------------------------------------------------------

## ۱۷. قرارداد LLM Client

LLM client در یک ماژول متمرکز است.

مفهوم API:

``` python
chat_json(system, user, schema_model)
```

مسئولیت‌ها:

-   ارتباط با OpenAI-compatible API؛
-   JSON Schema response format؛
-   Pydantic validation؛
-   timeout؛
-   تشخیص truncation؛
-   error reporting؛
-   retry محدود.

اگر:

``` text
finish_reason=length
```

باشد، پاسخ ناقص تلقی می‌شود و نباید با حدس یا parsing خوش‌بینانه معتبر فرض
شود.

### ۱۷.۱ انتخاب مدل

مدل از configuration می‌آید:

``` env
LLM_MODEL=...
```

fallback مخفی وجود ندارد.

این تصمیم مهم است، چون مدل‌ها از نظر JSON adherence و مصرف reasoning
token رفتار متفاوتی دارند.

تغییر model بنابراین یک تصمیم runtime/architecture است، نه یک تغییر جزئی
configuration.

------------------------------------------------------------------------

## ۱۸. Frontend

Frontend با:

-   Vue 3
-   TypeScript
-   Vite
-   Tailwind CSS
-   Pinia
-   Persian-first RTL

ساخته شده است.

ارتباط HTTP فقط از API layer انجام می‌شود.

Pinia فقط stateهایی را نگه می‌دارد که واقعاً بین viewها مشترک‌اند:

-   search؛
-   catalogue/cache؛
-   selection list.

Stateهای محلی کامپوننت‌ها داخل خود کامپوننت باقی می‌مانند.

### ۱۸.۱ Thinking States

Thinking States صرفاً یک UI component است:

``` text
states
activeIndex
visible
```

کامپوننت خودش request نمی‌فرستد.

Parent lifecycle واقعی search را به stateها متصل می‌کند.

برای جلو رفتن stateها timer مصنوعی وجود ندارد.

اگر LLM سی ثانیه طول بکشد، همان state به مدت سی ثانیه باقی می‌ماند.

Animation صرفاً feedback بصری است و نباید progress جعلی ایجاد کند.

------------------------------------------------------------------------

## ۱۹. Design System

UI به‌صورت Persian-first و RTL طراحی شده است.

اصول اصلی:

-   Material Design 2 به‌عنوان مرجع interaction/design؛
-   theme tokens مرکزی؛
-   typography مناسب فارسی؛
-   logical CSS properties؛
-   Persian number formatting؛
-   Toman formatting.

رنگ، radius، shadow و duration نباید به‌صورت arbitrary داخل componentها
hardcode شوند وقتی token متناظر وجود دارد.

برای animation نیز reduced-motion و accessibility در نظر گرفته شده است.

------------------------------------------------------------------------

## ۲۰. Pipeline داده

کاتالوگ demo به‌صورت مرحله‌ای ساخته شده:

``` text
raw Torob captures
       ↓
normalization
       ↓
انتخاب دستی محصولات
       ↓
canonical enrichment
       ↓
اتصال seller/offer
       ↓
products_70_enriched.json
```

raw data دست‌نخورده باقی می‌ماند.

کاتالوگ enriched یک artifact versioned و قابل review است.

این موضوع مهم است، چون vocabulary کاتالوگ مستقیماً روی deterministic
matching اثر می‌گذارد.

بنابراین تغییر vocabulary یک تغییر semantic در محصول است و باید مانند
تغییر code قابل بررسی باشد.

------------------------------------------------------------------------

## ۲۱. Dataset فعلی

کاتالوگ canonical فعلی شامل ۷۰ محصول است.

Domainها:

-   bathroom
-   kitchen
-   furniture
-   appliances

گروه‌های اصلی:

### Bathroom

-   شیر توالت
-   شیر روشویی
-   روشویی
-   توالت
-   آینه سرویس بهداشتی

### Kitchen

-   سینک ظرفشویی
-   شیر ظرفشویی
-   هود
-   اجاق
-   فر توکار

### Furniture

-   تخت
-   میز
-   صندلی ناهارخوری
-   میز ناهارخوری
-   مبل
-   کمد

### Appliances

-   یخچال
-   ماشین لباسشویی
-   ماشین ظرفشویی
-   تلویزیون
-   جاروبرقی
-   مایکروویو

Dataset عمداً کوچک نگه داشته شده تا semantics، matching و reasoning قابل
مشاهده و بررسی باشند.

------------------------------------------------------------------------

## ۲۲. محدودیت‌های فعلی

### پوشش ناقص کاتالوگ

همه چیزهایی که در یک پروژه واقعی خانه لازم است در dataset وجود ندارد.

برای مثال ممکن است نیازهایی مانند:

-   کاشی؛
-   عایق/ایزوگام یا waterproofing؛
-   لوله‌کشی؛
-   نورپردازی؛
-   رنگ

unmet بمانند.

این رفتار صحیح‌تر از جایگزین کردن آن‌ها با محصول نامرتبط است.

### کیفیت محصول

metadata کیفیت محصول کامل نیست.

اگر داده معتبر برای quality محصول وجود نداشته باشد، نباید quality ساختگی
به آن نسبت داده شود.

### برآورد هزینه

total پروژه صرفاً بر مبنای محصولات/مواد موجود در کاتالوگ است.

شامل موارد زیر نیست مگر اینکه صراحتاً مدل شوند:

-   دستمزد؛
-   نصب؛
-   margin پیمانکار؛
-   زمان‌بندی؛
-   پرت؛
-   حمل‌ونقل.

### مقیاس کاتالوگ

matcher فعلی برای dataset کوچک مناسب است.

در مقیاس بسیار بزرگ می‌توان لایه search را به PostgreSQL search یا search
engine منتقل کرد بدون اینکه مرزهای project/LLM تغییر کنند.

### تفاوت مدل‌ها

رفتار مدل‌های مختلف از نظر structured output و reasoning یکسان نیست.

مدلی که قبل از JSON وارد reasoning/narration طولانی شود ممکن است token
budget را تمام کند.

سیستم باید این failure را گزارش کند، نه اینکه نتیجه ساختگی تولید کند.

------------------------------------------------------------------------

## ۲۳. اصول مهندسی

1.  **اول deterministic، بعد probabilistic.**
2.  **حقیقت کاتالوگ مقدم بر خروجی مدل است.**
3.  **Hard constraint با code enforce می‌شود.**
4.  **LLM فقط context محدود دریافت می‌کند.**
5.  **Interpretation و product selection دو مسئولیت جدا هستند.**
6.  **Requirement محصول نیست.**
7.  **Quantity محصول در مدل فعلی وجود ندارد.**
8.  **Selection کاربر بی‌اجازه تغییر نمی‌کند.**
9.  **نبود محصول به‌صورت unmet باقی می‌ماند.**
10. **Mapping اختصاصی برای queryهای خاص ساخته نمی‌شود.**
11. **وقتی deterministic logic کافی است، LLM نباید صدا زده شود.**
12. **مشکل token با افزایش کورکورانه budget حل نمی‌شود.**
13. **Prompt باید با schema و مرزهای معماری سازگار بماند.**
14. **Testها باید invariantها و propertyها را محافظت کنند، نه فقط چند
    مثال ثابت را.**
15. **تغییرات کوچک و متمرکز بر rewriteهای چندلایه ترجیح دارند.**

------------------------------------------------------------------------

## ۲۴. راه‌اندازی

### Docker

``` bash
cp .env.example .env
docker compose up --build
```

آدرس‌های توسعه:

``` text
Frontend: http://localhost:5173
Backend:  http://localhost:8000
API docs: http://localhost:8000/docs
```

### Backend

``` bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

alembic upgrade head
python -m app.seed.run
uvicorn app.main:app --reload
```

### Frontend

``` bash
cd frontend
npm install
npm run dev
```

### Test

``` bash
make test
```

یا:

``` bash
cd backend && .venv/bin/python -m pytest -q
cd frontend && npm run test:run
cd frontend && npm run typecheck
```

------------------------------------------------------------------------

## ۲۵. متغیرهای مهم محیطی

``` env
DATABASE_URL=postgresql+psycopg://torob:torob@localhost:5432/torob_home

PRODUCT_SOURCE=local
TOROB_MCP_URL=https://torob-mcp.sajjadbayatani.workers.dev/mcp

LLM_API_KEY=
LLM_MODEL=
LLM_BASE_URL=
LLM_TEMPERATURE=0
LLM_REASONING_EFFORT=low
LLM_MAX_TOKENS=2000

CATALOG_PATH=../data/catalog/products_70_enriched.json
VITE_API_BASE_URL=http://localhost:8000/api/v1
```

لیست کامل configuration همان `.env.example` است.

------------------------------------------------------------------------

## ۲۶. ساختار repository

``` text
backend/
├── app/
│   ├── core/
│   ├── db/
│   ├── catalog/
│   ├── llm/
│   ├── seed/
│   └── domains/
│       ├── catalog/
│       ├── sellers/
│       ├── search/
│       ├── projects/
│       └── basket/
├── alembic/
└── tests/

frontend/
├── src/
│   ├── api/
│   ├── stores/
│   ├── composables/
│   ├── components/
│   ├── views/
│   ├── theme/
│   ├── types/
│   └── utils/
└── tests/

data/
├── raw/
├── product-pages/
└── catalog/

scripts/
docs/
docker-compose.yml
Makefile
.env.example
```

------------------------------------------------------------------------

## ۲۷. وضعیت معماری

مرز اصلی سیستم در وضعیت فعلی این است:

``` text
زبان کاربر
     ↓
semantic interpretation
     ↓
ساختار search/project
     ↓
resolution قطعی روی catalogue
     ↓
candidateهای محدود
     ↓
LLM reasoning در صورت نیاز
     ↓
validation
     ↓
نتیجه قابل استفاده برای کاربر
```

هدف معماری این است که با افزایش تعداد محصولات، اضافه شدن sourceهای جدید،
بهتر شدن matcher یا تغییر مدل reasoning، authority مربوط به محصولات و
داده‌های واقعی هیچ‌وقت به LLM منتقل نشود.

------------------------------------------------------------------------

## داده و مجوز

این repository یک prototype است. اطلاعات محصولات از listingهای ثبت‌شده در
Torob تهیه شده و حقوق و شرایط استفاده از داده‌های محصول و فروشنده‌ها تابع
منابع مربوطه است.
