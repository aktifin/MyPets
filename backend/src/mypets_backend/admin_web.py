"""Static administrator console routes with restrictive browser security headers."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

admin_web_router = APIRouter(include_in_schema=False)
_WEB_ROOT = Path(__file__).with_name("admin_console_static")
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; "
        "connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    ),
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _asset(name: str, media_type: str) -> FileResponse:
    path = (_WEB_ROOT / name).resolve()
    if path.parent != _WEB_ROOT.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="管理台资源不存在")
    return FileResponse(path, media_type=media_type, headers=_SECURITY_HEADERS)


@admin_web_router.get("/admin")
@admin_web_router.get("/admin/")
def admin_console() -> FileResponse:
    return _asset("index.html", "text/html; charset=utf-8")


@admin_web_router.get("/admin/app.js")
def admin_console_script() -> FileResponse:
    return _asset("app.js", "text/javascript; charset=utf-8")


@admin_web_router.get("/admin/styles.css")
def admin_console_styles() -> FileResponse:
    return _asset("styles.css", "text/css; charset=utf-8")
