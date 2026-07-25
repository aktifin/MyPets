"""Role and permission enforcement for administrator HTTP routes."""

from __future__ import annotations

import re
from collections.abc import Iterable

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from .models import Account
from .security import decode_access_token

ROLE_PERMISSIONS: dict[str, frozenset[str]] = {
    "editor": frozenset({"view", "edit"}),
    "reviewer": frozenset({"view", "review"}),
    "publisher": frozenset({"view", "publish"}),
    "auditor": frozenset({"view", "audit"}),
    "superadmin": frozenset({"view", "edit", "review", "publish", "audit", "manage"}),
}


def permissions_for_roles(roles: Iterable[str]) -> tuple[str, ...]:
    permissions = {
        permission
        for role in roles
        for permission in ROLE_PERMISSIONS.get(role, frozenset())
    }
    return tuple(sorted(permissions))


def _required_permission(method: str, path: str) -> str:
    if method == "GET":
        if path == "/api/v1/admin/audit-logs":
            return "audit"
        return "view"
    if method == "POST":
        if path == "/api/v1/admin/pet-templates":
            return "edit"
        if re.fullmatch(r"/api/v1/admin/pet-templates/[^/]+/versions", path):
            return "edit"
        if re.fullmatch(
            r"/api/v1/admin/pet-template-versions/[^/]+/(package|submit-review)", path
        ):
            return "edit"
        if re.fullmatch(
            r"/api/v1/admin/pet-template-versions/[^/]+/(approve|reject)", path
        ):
            return "review"
        if re.fullmatch(r"/api/v1/admin/pet-template-versions/[^/]+/publish", path):
            return "publish"
        if re.fullmatch(r"/api/v1/admin/pet-asset-deployments/[^/]+/rollback", path):
            return "publish"
        if re.fullmatch(
            r"/api/v1/admin/pet-asset-submissions/[^/]+/start-review", path
        ):
            return "edit"
        if re.fullmatch(
            r"/api/v1/admin/pet-asset-submissions/[^/]+/(approve|reject)", path
        ):
            return "review"
        if re.fullmatch(
            r"/api/v1/admin/pet-asset-production-jobs/[^/]+/(assign|update|artifact)",
            path,
        ):
            return "edit"
    return "manage"


class AdminPermissionMiddleware(BaseHTTPMiddleware):
    """Apply role-specific authorization before protected administrator endpoints.

    Authentication errors are intentionally delegated to the existing FastAPI
    dependencies. This middleware only rejects a valid administrator account that
    lacks the permission required by the requested administrator operation.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        path = request.url.path
        if not path.startswith("/api/v1/admin") or request.method == "OPTIONS":
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return await call_next(request)

        settings = request.app.state.settings
        try:
            principal = decode_access_token(token, settings)
        except jwt.PyJWTError:
            return await call_next(request)
        if principal.kind != "account":
            return await call_next(request)

        with request.app.state.session_factory() as session:
            account = session.get(Account, principal.account_id)
            if account is None:
                return await call_next(request)
            roles = settings.roles_for_username(account.username)

        if not roles:
            return await call_next(request)

        permissions = permissions_for_roles(roles)
        required = _required_permission(request.method, path)
        request.state.admin_roles = roles
        request.state.admin_permissions = permissions
        if required not in permissions:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "当前管理员角色无权执行此操作",
                    "required_permission": required,
                },
                headers={"Cache-Control": "no-store"},
            )
        return await call_next(request)
