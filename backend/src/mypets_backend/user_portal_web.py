"""Static user portal routes with restrictive browser security headers."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

user_portal_web_router = APIRouter(include_in_schema=False)
_WEB_ROOT = Path(__file__).with_name("user_portal_static")
_SECURITY_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
        "connect-src 'self' ws: wss:; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
        "form-action 'self'"
    ),
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def _path(name: str) -> Path:
    path = (_WEB_ROOT / name).resolve()
    if path.parent != _WEB_ROOT.resolve() or not path.is_file():
        raise HTTPException(status_code=404, detail="用户门户资源不存在")
    return path


def _asset(name: str, media_type: str) -> FileResponse:
    return FileResponse(_path(name), media_type=media_type, headers=_SECURITY_HEADERS)


@user_portal_web_router.get("/portal")
@user_portal_web_router.get("/portal/")
def user_portal() -> HTMLResponse:
    html = _path("index.html").read_text(encoding="utf-8")
    marker = "</head>"
    realtime_script = '<script src="/portal/realtime.js" defer></script>'
    if realtime_script not in html:
        html = html.replace(marker, f"  {realtime_script}\n{marker}", 1)
    return HTMLResponse(html, headers=_SECURITY_HEADERS)


@user_portal_web_router.get("/portal/app.js")
def user_portal_script() -> FileResponse:
    return _asset("app.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/visits.js")
def user_portal_visits_script() -> FileResponse:
    return _asset("visits.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/realtime.js")
def user_portal_realtime_script() -> FileResponse:
    return _asset("realtime.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/styles.css")
def user_portal_styles() -> FileResponse:
    return _asset("styles.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/visits.css")
def user_portal_visits_styles() -> FileResponse:
    return _asset("visits.css", "text/css; charset=utf-8")
