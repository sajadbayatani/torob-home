"""The catalog domain has no tables.

Products, categories, brands, attributes, relations, sellers and offers all come
from `data/catalog/products.json`, which `app.catalog` reads. The database keeps
only what the *application* owns: baskets, project templates, requirement rules
and analyses.

This module is kept as the documented seam: anything that needs to know the
catalogue is not in the database should import `app.catalog`, not reach for a
table.
"""

from app.catalog.store import CatalogIndex, CatalogProduct, get_catalog

__all__ = ["CatalogIndex", "CatalogProduct", "get_catalog"]
