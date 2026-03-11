import os
import sys
import time
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from alembic import command
from alembic.config import Config

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _get_database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def _alembic_config(database_url: str) -> Config:
    config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    alembic_config = Config(str(config_path))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    return alembic_config


def _wait_for_db(database_url: str, timeout_seconds: int = 60, interval: float = 2.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            engine = create_engine(
                database_url,
                connect_args={"connect_timeout": 5, "options": "-c statement_timeout=30000"},
                pool_pre_ping=True,
            )
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(interval)
    raise RuntimeError("Database did not become ready in time") from last_error


@pytest.fixture(scope="session")
def db_engine():
    database_url = _get_database_url()
    if not database_url:
        pytest.skip("DATABASE_URL is not set")

    print("Waiting for database to become ready...", flush=True)
    _wait_for_db(database_url)
    engine = create_engine(
        database_url,
        connect_args={"connect_timeout": 5, "options": "-c statement_timeout=30000"},
        pool_pre_ping=True,
    )
    print("Running Alembic migrations...", flush=True)
    command.upgrade(_alembic_config(database_url), "head")
    print("Migrations complete.", flush=True)
    return engine


@pytest.fixture()
def db_connection(db_engine):
    with db_engine.begin() as connection:
        connection.execute(text("SET statement_timeout = '30s'"))
        connection.execute(
            text(
                "TRUNCATE TABLE ratings, routes, segments, users RESTART IDENTITY CASCADE"
            )
        )
        yield connection
