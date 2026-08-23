import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Keep every test on one timezone regardless of the machine running them.
os.environ.setdefault("TIMEZONE", "America/New_York")

# Warehouse tests need a real Postgres. Point TEST_DATABASE_URL at any empty
# database (a local one, or a Supabase branch) and they run against it; without
# it they skip rather than pretending to pass. CI should always set it.
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("set TEST_DATABASE_URL to run the warehouse tests")
    pytest.importorskip("psycopg")
    return TEST_DATABASE_URL


@pytest.fixture
def warehouse(database_url):
    """A warehouse on a freshly created schema, dropped after the test."""
    import psycopg

    from src.warehouse import Warehouse

    with psycopg.connect(database_url, autocommit=True) as setup:
        setup.execute("drop schema if exists kpi cascade")

    wh = Warehouse(dsn=database_url)
    wh.apply_schema()
    try:
        yield wh
    finally:
        wh.close()
        with psycopg.connect(database_url, autocommit=True) as teardown:
            teardown.execute("drop schema if exists kpi cascade")
