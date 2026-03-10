import os
import sys
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _get_database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def _alembic_config(database_url: str) -> Config:
    config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
    alembic_config = Config(str(config_path))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    return alembic_config


@pytest.fixture(scope="session")
def db_engine():
    database_url = _get_database_url()
    if not database_url:
        pytest.skip("DATABASE_URL is not set")

    engine = create_engine(database_url)
    command.upgrade(_alembic_config(database_url), "head")
    return engine


@pytest.fixture()
def db_connection(db_engine):
    with db_engine.begin() as connection:
        connection.execute(
            text(
                "TRUNCATE TABLE ratings, routes, segments, users RESTART IDENTITY CASCADE"
            )
        )
        yield connection
