"""Alembic migration environment for MyPets backend SQLAlchemy models."""

from __future__ import annotations

from logging.config import fileConfig
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src")))

from mypets_backend.database import Base
from mypets_backend import models  # noqa: F401
from mypets_backend import social_models  # noqa: F401
from mypets_backend import visit_models  # noqa: F401
from mypets_backend import reminder_models  # noqa: F401
from mypets_backend import user_portal_models  # noqa: F401
from mypets_backend import asset_submission_models  # noqa: F401
from mypets_backend import asset_production_models  # noqa: F401
from mypets_backend import asset_deployment_models  # noqa: F401

config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = os.getenv("MYPETS_DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = os.getenv("MYPETS_DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
