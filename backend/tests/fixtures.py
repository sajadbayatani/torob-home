"""A small catalogue for the tests, in the real `products.json` shape.

The suite must not depend on the 70-product production catalogue: a rebuild of
`data/catalog/products.json` must not be able to break or silently pass the
tests. This fixture is written to a temporary file and pointed at through
`CATALOG_PATH`, so the tests exercise the same loader, validator and projections
the API uses.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.catalog.store import reset_cache

#: two subcategories, two top-level categories, real and absent brands
CATALOG: list[dict] = [
    {
        "id": "11111111-1111-4111-8111-111111111111",
        "category": "bathroom",
        "subcategory": "sink-faucet",
        "name": "شیر روشویی کاسا مدل K-100",
        "brand": "کاسا",
        "model": "K-100",
        "attributes": {"color": "کروم", "installation": "توکار"},
        "lowest_price_toman": 5_900_000,
        "image_url": "https://image.torob.com/base/images/faucet.jpg",
        "source": {
            "name": "torob",
            "url": "https://torob.com/p/11111111-1111-4111-8111-111111111111",
        },
        "offers": [
            {
                "prk": "aaaaaaaa-0000-4000-8000-000000000001",
                "shop_id": 101,
                "shop_name": "بازار ساختمان",
                "shop_name2": "تهران",
                "price": 5_900_000,
                "price_text_mode": "active",
                "availability": True,
                "is_price_unreliable": False,
                "page_url": "https://torob.com/p/aaaaaaaa-0000-4000-8000-000000000001",
                "last_price_change_date": "۴ روز پیش",
            },
            {
                "prk": "aaaaaaaa-0000-4000-8000-000000000002",
                "shop_id": 102,
                "shop_name": "لوله و اتصالات",
                "shop_name2": "اصفهان",
                "price": 6_667_000,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/aaaaaaaa-0000-4000-8000-000000000002",
                "last_price_change_date": "۱ ماه پیش",
            },
        ],
    },
    {
        "id": "22222222-2222-4222-8222-222222222222",
        "category": "bathroom",
        "subcategory": "sink-faucet",
        "name": "شیر روشویی قهرمان مدل تندیس کروم",
        "brand": "قهرمان",
        "model": "تندیس",
        "attributes": {"color": "کروم"},
        "lowest_price_toman": 7_550_000,
        "image_url": "https://image.torob.com/base/images/qahroman.jpg",
        "source": {
            "name": "torob",
            "url": "https://torob.com/p/22222222-2222-4222-8222-222222222222",
        },
        "offers": [
            {
                "prk": "bbbbbbbb-0000-4000-8000-000000000001",
                "shop_id": 103,
                "shop_name": "فروشگاه قهرمان",
                "shop_name2": "تهران",
                "price": 7_550_000,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/bbbbbbbb-0000-4000-8000-000000000001",
            }
        ],
    },
    {
        # a cheaper faucet, so budget optimisation has a real alternative to
        # swap towards: same subcategory, lower price
        "id": "66666666-6666-4666-8666-666666666666",
        "category": "bathroom",
        "subcategory": "sink-faucet",
        "name": "شیر روشویی مروارید مدل کروم",
        "brand": "مروارید",
        "model": "M-20",
        "attributes": {"color": "کروم"},
        "lowest_price_toman": 4_100_000,
        "image_url": "https://image.torob.com/base/images/morvarid.jpg",
        "source": {
            "name": "torob",
            "url": "https://torob.com/p/66666666-6666-4666-8666-666666666666",
        },
        "offers": [
            {
                "prk": "eeeeeeee-0000-4000-8000-000000000001",
                "shop_id": 107,
                "shop_name": "بازار لوازم بهداشتی",
                "shop_name2": "تهران",
                "price": 4_100_000,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/eeeeeeee-0000-4000-8000-000000000001",
            }
        ],
    },
    {
        "id": "33333333-3333-4333-8333-333333333333",
        "category": "bathroom",
        "subcategory": "toilet",
        "name": "توالت ایرانی گلچین",
        "brand": None,
        "model": None,
        "attributes": {},
        "lowest_price_toman": 3_200_000,
        "image_url": "https://image.torob.com/base/images/toilet.jpg",
        "source": {
            "name": "torob",
            "url": "https://torob.com/p/33333333-3333-4333-8333-333333333333",
        },
        "offers": [
            {
                "prk": "cccccccc-0000-4000-8000-000000000001",
                "shop_id": 104,
                "shop_name": "لوله‌باز",
                "shop_name2": "شیراز",
                "price": 3_200_000,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/cccccccc-0000-4000-8000-000000000001",
            },
            # unavailable: the page marks it ناموجود, so it is not an offer
            {
                "prk": "cccccccc-0000-4000-8000-000000000002",
                "shop_id": 105,
                "shop_name": "فروش ناموجود",
                "price": 0,
                "price_text": "ناموجود",
                "price_text_mode": "disabled",
                "availability": False,
            },
        ],
    },
    {
        "id": "44444444-4444-4444-8444-444444444444",
        "category": "kitchen",
        "subcategory": "kitchen-hood",
        "name": "هود آشپزخانه اخوان مدل H21",
        "brand": "اخوان",
        "model": "H21",
        "attributes": {"color": "استیل"},
        "lowest_price_toman": 12_500_000,
        "image_url": "https://image.torob.com/base/images/hood.jpg",
        "source": {
            "name": "torob",
            "url": "https://torob.com/p/44444444-4444-4444-8444-444444444444",
        },
        "offers": [
            {
                "prk": "dddddddd-0000-4000-8000-000000000001",
                "shop_id": 106,
                "shop_name": "لوازم برقی تهران",
                "shop_name2": "تهران",
                "price": 12_500_000,
                "price_text_mode": "active",
                "availability": True,
                "is_price_unreliable": True,
                "page_url": "https://torob.com/p/dddddddd-0000-4000-8000-000000000001",
            }
        ],
    },
    {
        # a cheaper toilet, so a project basket has something to optimise towards
        "id": "abababab-abab-4bab-8bab-abababababab",
        "category": "bathroom",
        "subcategory": "toilet",
        "name": "توالت ایرانی سنگی باغی",
        "brand": None,
        "model": None,
        "attributes": {},
        "lowest_price_toman": 2_400_000,
        "image_url": "https://image.torob.com/base/images/toilet-cheap.jpg",
        "source": {
            "name": "torob",
            "url": "https://torob.com/p/abababab-abab-4bab-8bab-abababababab",
        },
        "offers": [
            {
                "prk": "abababab-0000-4000-8000-000000000001",
                "shop_id": 110,
                "shop_name": "سفال فروشی باغی",
                "shop_name2": "تبریز",
                "price": 2_400_000,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/abababab-0000-4000-8000-000000000001",
            }
        ],
    },
    {
        # a washbasin and a mirror, so a bathroom project has candidates for the
        # vanity and mirror requirements as well as the toilet and faucet
        "id": "77777777-7777-4777-8777-777777777777",
        "category": "bathroom",
        "subcategory": "sink",
        "name": "روشویی کابینتی پارس سرام مدل تونی",
        "brand": "پارس سرام",
        "model": "تونی",
        "attributes": {"color": "سفید", "installation": "توکار"},
        "lowest_price_toman": 2_077_650,
        "image_url": "https://image.torob.com/base/images/sink.jpg",
        "source": {
            "name": "torob",
            "url": "https://torob.com/p/77777777-7777-4777-8777-777777777777",
        },
        "offers": [
            {
                "prk": "ffffffff-0000-4000-8000-000000000001",
                "shop_id": 108,
                "shop_name": "سرامیک پارس",
                "shop_name2": "تهران",
                "price": 2_077_650,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/ffffffff-0000-4000-8000-000000000001",
            }
        ],
    },
    {
        "id": "88888888-8888-4888-8888-888888888888",
        "category": "bathroom",
        "subcategory": "bathroom-mirror",
        "name": "آینه سرویس بهداشتی مدل سارینا",
        "brand": "دلفین",
        "model": "سارینا",
        "attributes": {"dimensions_cm": "60x80"},
        "lowest_price_toman": 1_480_000,
        "image_url": "https://image.torob.com/base/images/mirror.jpg",
        "source": {
            "name": "torob",
            "url": "https://torob.com/p/88888888-8888-4888-8888-888888888888",
        },
        "offers": [
            {
                "prk": "99999999-0000-4000-8000-000000000001",
                "shop_id": 109,
                "shop_name": "آینه سازیeast",
                "shop_name2": "کرج",
                "price": 1_480_000,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/99999999-0000-4000-8000-000000000001",
            }
        ],
    },
    # --- furniture: the real catalogue stocks a furniture category, and the
    # --- interpreter is shown the catalogue's taxonomy, so the fixture has to
    # --- cover it too. Without this, a "changing my bedroom" query has nothing
    # --- to map onto and the test would be testing an empty catalogue.
    {
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1",
        "category": "furniture",
        "subcategory": "bed",
        "name": "تخت خواب چوبی مدل آریا",
        "brand": "آریا",
        "model": "آریا",
        "attributes": {"dimensions_cm": "160x200"},
        "lowest_price_toman": 8_900_000,
        "image_url": "https://image.torob.com/base/images/bed.jpg",
        "source": {"name": "torob", "url": "https://torob.com/p/bed"},
        "offers": [
            {
                "prk": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb2",
                "shop_id": 110,
                "shop_name": "فروشگاه چوب و هنر",
                "shop_name2": "تهران",
                "price": 8_900_000,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/bed-offer",
            }
        ],
    },
    {
        "id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3",
        "category": "furniture",
        "subcategory": "wardrobe",
        "name": "کمد لباس چوبی مدل آریا",
        "brand": "آریا",
        "model": "آریا",
        "attributes": {"dimensions_cm": "180x60"},
        "lowest_price_toman": 6_400_000,
        "image_url": "https://image.torob.com/base/images/wardrobe.jpg",
        "source": {"name": "torob", "url": "https://torob.com/p/wardrobe"},
        "offers": [
            {
                "prk": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb4",
                "shop_id": 110,
                "shop_name": "فروشگاه چوب و هنر",
                "shop_name2": "تهران",
                "price": 6_400_000,
                "price_text_mode": "active",
                "availability": True,
                "page_url": "https://torob.com/p/wardrobe-offer",
            }
        ],
    },
    # --- records that must be dropped, with a reason ---------------------
    {"id": "", "name": "بدون شناسه", "lowest_price_toman": 10, "image_url": "https://x/y.jpg"},
    {
        "id": "55555555-5555-4555-8555-555555555555",
        "name": "بدون قیمت",
        "lowest_price_toman": 0,
        "image_url": "https://x/y.jpg",
    },
]

#: ids the tests can rely on
FAUCET_ID = "11111111-1111-4111-8111-111111111111"
FAUCET_QAHRMAN_ID = "22222222-2222-4222-8222-222222222222"
TOILET_ID = "33333333-3333-4333-8333-333333333333"
HOOD_ID = "44444444-4444-4444-8444-444444444444"
CHEAPER_FAUCET_ID = "66666666-6666-4666-8666-666666666666"
CHEAPER_TOILET_ID = "abababab-abab-4bab-8bab-abababababab"
SINK_ID = "77777777-7777-4777-8777-777777777777"
MIRROR_ID = "88888888-8888-4888-8888-888888888888"
BED_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb1"
WARDROBE_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb3"
FAUCET_FIRST_OFFER = "aaaaaaaa-0000-4000-8000-000000000001"


@pytest.fixture(scope="session", autouse=True)
def catalog_file(tmp_path_factory) -> Iterator[Path]:
    """Point the catalogue at a fixture file for the whole session."""
    path = tmp_path_factory.mktemp("catalog") / "products.json"
    path.write_text(json.dumps(CATALOG, ensure_ascii=False), encoding="utf-8")
    import os

    previous = os.environ.get("CATALOG_PATH")
    os.environ["CATALOG_PATH"] = str(path)
    # settings are cached, so rebuild them and drop any cached catalogue read
    from app.core.config import get_settings

    get_settings.cache_clear()
    reset_cache()
    yield path
    if previous is None:
        os.environ.pop("CATALOG_PATH", None)
    else:
        os.environ["CATALOG_PATH"] = previous
    get_settings.cache_clear()
    reset_cache()
