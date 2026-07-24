"""FastAPI application factory for the MyPets modular monolith."""

from __future__ import annotations

from fastapi import FastAPI

from .admin_api import admin_router, catalog_router
from .api import router
from .config import Settings
from .database import Base, create_database_engine, create_session_factory
from .object_store import FileObjectStore


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    resolved.validate()
    engine = create_database_engine(resolved)
    session_factory = create_session_factory(engine)
    if resolved.create_schema_on_start:
        Base.metadata.create_all(engine)

    app = FastAPI(
        title="MyPets API",
        version="0.1.0",
        description=(
            "Server-authoritative account, device, pet, synchronization, and pet asset publishing API."
        ),
    )
    app.state.settings = resolved
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.asset_object_store = FileObjectStore(resolved.asset_storage_path)
    app.include_router(router)
    app.include_router(admin_router)
    app.include_router(catalog_router)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
