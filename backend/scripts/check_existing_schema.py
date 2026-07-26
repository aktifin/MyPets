"""Compare an existing database schema with the complete MyPets SQLAlchemy metadata.

Run this before ``alembic stamp head`` when adopting a database that was historically
created with ``Base.metadata.create_all``. The command exits non-zero when Alembic detects
missing tables, extra tables, column/type/default differences, or constraint/index drift.
"""

from __future__ import annotations

import os
import sys
from pprint import pformat

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from mypets_backend.database import Base
from mypets_backend import asset_deployment_models  # noqa: F401
from mypets_backend import asset_production_models  # noqa: F401
from mypets_backend import asset_submission_models  # noqa: F401
from mypets_backend import governance_models  # noqa: F401
from mypets_backend import models  # noqa: F401
from mypets_backend import reminder_models  # noqa: F401
from mypets_backend import social_models  # noqa: F401
from mypets_backend import user_portal_models  # noqa: F401
from mypets_backend import visit_models  # noqa: F401


def compare_schema(database_url: str) -> list[object]:
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(
                connection,
                opts={
                    "compare_type": True,
                    "compare_server_default": True,
                    "include_schemas": False,
                    "version_table": "alembic_version",
                },
            )
            return list(compare_metadata(context, Base.metadata))
    finally:
        engine.dispose()


def main() -> int:
    database_url = os.getenv("MYPETS_DATABASE_URL", "").strip()
    if not database_url:
        print("MYPETS_DATABASE_URL is required.", file=sys.stderr)
        return 2

    differences = compare_schema(database_url)
    if differences:
        print("Existing database schema does not match MyPets metadata:", file=sys.stderr)
        for difference in differences:
            print(f"- {pformat(difference, width=120)}", file=sys.stderr)
        return 1

    print("Existing database schema matches MyPets metadata.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
