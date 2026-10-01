"""Pytest fixtures.

The suite runs against a **real PostgreSQL** (the spec mandates PostgreSQL), using
a dedicated test database.

The product catalogue is **not** in the database: it is a JSON file the backend
reads. `tests/fixtures.py` points `CATALOG_PATH` at a small catalogue for the
session, so the tests never depend on the production `data/catalog/products.json`
and a catalogue rebuild cannot change a test result. Only the reference data the
database owns (project templates and requirement rules) is seeded, and only the
mutable tables are truncated between tests.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

TEST_DB_NAME = "torob_home_test"
DEFAULT_URL = "postgresql+psycopg://torob:torob@localhost:5432/" + TEST_DB_NAME


def _resolve_test_url() -> str:
    """Pick the test database URL.

    Priority: ``TEST_DATABASE_URL`` env var → ``DATABASE_URL`` env var → local
    default. Docker service hostnames are rewritten to localhost unless we are
    actually running inside a container, so ``make test-backend`` works on the
    host with the shipped ``.env``.
    """
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL") or DEFAULT_URL
    if "@postgres:" in url and not Path("/.dockerenv").exists():
        url = url.replace("@postgres:", "@localhost:")
    if url.rsplit("/", 1)[-1] != TEST_DB_NAME:
        url = url.rsplit("/", 1)[0] + "/" + TEST_DB_NAME
    return url


TEST_DATABASE_URL = _resolve_test_url()
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["TEST_DATABASE_URL"] = TEST_DATABASE_URL
# The interpreter is the LLM and there is no keyword fallback, so the suite
# always has a usable (fake) configuration; `tests/llm_stub.py` intercepts the
# HTTP call itself so the real client and parsing still run.
os.environ.setdefault("LLM_API_KEY", "test-key-not-real")
os.environ.setdefault("LLM_MODEL", "test/model")
# The suite stubs the HTTP call, but the client still needs an endpoint to build,
# and the setting has no vendor default on purpose.
os.environ.setdefault("LLM_BASE_URL", "https://openrouter.test/api/v1")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_session_factory, reset_engine  # noqa: E402
from app.main import app  # noqa: E402

MUTABLE_TABLES = ("basket_items", "baskets", "project_analyses")

# `catalog_file` is session-scoped and autouse: it repoints the catalogue at a
# fixture before any test reads it. It must be imported by name for pytest to
# collect it from this conftest.
from tests.fixtures import catalog_file  # noqa: E402,F401
from tests.llm_stub import llm  # noqa: E402,F401


def _ensure_database() -> None:
    base_url = TEST_DATABASE_URL.rsplit("/", 1)[0]
    admin_url = base_url + "/postgres"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("select 1 from pg_database where datname = :name"), {"name": TEST_DB_NAME}
        ).scalar()
        if not exists:
            conn.execute(text(f'create database "{TEST_DB_NAME}"'))
    admin.dispose()


def _recreate_database() -> None:
    """Drop and recreate the test database so the schema matches the models."""
    base_url = TEST_DATABASE_URL.rsplit("/", 1)[0]
    admin = create_engine(base_url + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(
            text(
                "select pg_terminate_backend(pid) from pg_stat_activity "
                "where datname = :name and pid <> pg_backend_pid()"
            ),
            {"name": TEST_DB_NAME},
        )
        conn.execute(text(f'drop database if exists "{TEST_DB_NAME}"'))
        conn.execute(text(f'create database "{TEST_DB_NAME}"'))
    admin.dispose()


@pytest.fixture(scope="session")
def engine():
    """A test database built from the current models.

    The database is **recreated**, not patched: the catalogue used to live in
    tables that the models no longer declare, and `drop_all` cannot remove a table
    it does not know about (nor the enum types those tables depended on). Starting
    from an empty database keeps the schema exactly in step with the models.
    """
    _recreate_database()
    reset_engine()
    eng = create_engine(TEST_DATABASE_URL, pool_pre_ping=True, future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session", autouse=True)
def seeded(engine) -> None:
    """Seed the reference data the database owns: templates and requirements."""
    from app.seed.run import seed

    with Session(engine) as session:
        counts = seed(session)
        session.commit()
    # the catalogue is never seeded
    assert counts["products"] == 0 if "products" in counts else True


@pytest.fixture(autouse=True)
def clean_mutable_tables(engine):
    with engine.begin() as conn:
        conn.execute(
            text("truncate table " + ", ".join(MUTABLE_TABLES) + " restart identity cascade")
        )
    yield


@pytest.fixture
def session(engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as db:
        yield db


@pytest.fixture
def client() -> Iterator[TestClient]:
    reset_engine()
    factory = get_session_factory()
    with TestClient(app) as test_client:
        yield test_client
    reset_engine()
    assert factory is not None
