"""MyPets 模块化单体、用户门户与 Web 管理端 FastAPI 应用工厂。"""

from __future__ import annotations

import os
from uuid import uuid4

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .admin_api import admin_router, catalog_router
from .admin_console_api import admin_console_api_router
from .admin_governance_api import admin_governance_router, governance_catalog_router
from .admin_rbac import AdminPermissionMiddleware
from .admin_web import admin_web_router
from .api import router
from .config import Settings
from .database import Base, create_database_engine, create_session_factory
from .messaging_api import messaging_router
from .models import Account
from .object_store import FileObjectStore
from .pet_care_api import pet_care_router
from .reminder_api import reminder_router
from .reminder_integration_api import reminder_integration_router
from .reminder_snapshot_api import reminder_snapshot_router
from .security import hash_password, normalize_username
from .settlement_middleware import PetSettlementMiddleware
from .social_api import social_router
from .user_portal_api import user_portal_api_router
from .user_portal_web import user_portal_web_router
from .visit_api import visit_router


def _seed_default_admins(session_factory: sessionmaker, admin_usernames: tuple[str, ...]) -> None:
    if os.getenv("PYTEST_CURRENT_TEST") or not admin_usernames:
        return
    targets = [
        ("pet_editor", "AdminEditor123!", "Pet Editor (Admin)"),
        ("pet_reviewer", "AdminReviewer123!", "Pet Reviewer (Admin)"),
    ]
    with session_factory() as session:
        for username, default_pass, display_name in targets:
            norm_name = normalize_username(username)
            if norm_name in admin_usernames and not session.scalar(
                select(Account.id).where(Account.username == norm_name)
            ):
                account = Account(
                    id=str(uuid4()),
                    username=norm_name,
                    display_name=display_name,
                    password_hash=hash_password(default_pass),
                )
                session.add(account)
        session.commit()


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    resolved.validate()
    engine = create_database_engine(resolved)
    session_factory = create_session_factory(engine)
    if resolved.create_schema_on_start:
        Base.metadata.create_all(engine)
        _seed_default_admins(session_factory, resolved.admin_usernames)

    app = FastAPI(
        title="MyPets API",
        version="0.2.0-alpha",
        description=(
            "Server-authoritative accounts, user Web portal, pets, friendship, shared care, "
            "asynchronous pet visits, lazy settlement, messaging, reminders, external reminder "
            "providers, synchronization, pet asset publishing, administrator governance, and "
            "console API."
        ),
    )
    app.state.settings = resolved
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.asset_object_store = FileObjectStore(resolved.asset_storage_path)
    app.add_middleware(AdminPermissionMiddleware)
    app.add_middleware(PetSettlementMiddleware)
    app.include_router(router)
    app.include_router(user_portal_api_router)
    app.include_router(pet_care_router)
    app.include_router(social_router)
    app.include_router(visit_router)
    app.include_router(messaging_router)
    app.include_router(reminder_router)
    app.include_router(reminder_snapshot_router)
    app.include_router(reminder_integration_router)
    # Static governance paths such as /pet-template-versions/compare must be
    # registered before admin_router's dynamic /{version_id} route.
    app.include_router(admin_governance_router)
    app.include_router(admin_router)
    app.include_router(admin_console_api_router)
    app.include_router(catalog_router)
    app.include_router(governance_catalog_router)
    app.include_router(user_portal_web_router)
    app.include_router(admin_web_router)

    @app.get("/")
    def index() -> RedirectResponse:
        return RedirectResponse(url="/portal")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
