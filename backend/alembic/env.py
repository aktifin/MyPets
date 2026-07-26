"""Alembic migration environment for the complete MyPets SQLAlchemy model registry."""

from __future__ import annotations

from logging.config import fileConfig
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from mypets_backend.database import Base
from mypets_backend import asset_deployment_models  # noqa: F401,E402
from mypets_backend import asset_production_models  # noqa: F401,E402
from mypets_backend import asset_submission_models  # noqa: F401,E402
from mypets_backend import governance_models  # noqa: F401,E402
from mypets_backend import models  # noqa: F401,E402
from mypets_backend import reminder_models  # noqa: F401,E402
from mypets_backend import social_models  # noqa: F401,E402
from mypets_backend import user_portal_models  # noqa: F401,E402
from mypets_backend import visit_models  # noqa: F401,E402

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return os.getenv("MYPETS_DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def _configure(connection=None, *, url: str | None = None) -> None:
    dialect_name = connection.dialect.name if connection is not None else (_database_url().split(":", 1)[0])
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=dialect_name == "sqlite",
        include_schemas=False,
        version_table="alembic_version",
    )


def run_migrations_offline() -> None:
    url = _database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=url.startswith("sqlite"),
        include_schemas=False,
        version_table="alembic_version",
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _database_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        _configure(connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
