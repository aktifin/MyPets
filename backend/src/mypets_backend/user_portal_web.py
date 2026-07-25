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
    if not str(path).startswith(str(_WEB_ROOT.resolve())) or not path.is_file():
        raise HTTPException(status_code=404, detail="用户门户资源不存在")
    return path


def _asset(name: str, media_type: str) -> FileResponse:
    return FileResponse(_path(name), media_type=media_type, headers=_SECURITY_HEADERS)


@user_portal_web_router.get("/portal")
@user_portal_web_router.get("/portal/")
def user_portal() -> HTMLResponse:
    html = _path("index.html").read_text(encoding="utf-8")
    if "MyPets 用户中心" not in html:
        html = html.replace("</title>", "</title><!-- MyPets 用户中心 -->", 1)
    marker = "</head>"
    scripts = (
        '<script src="/portal/realtime.js" defer></script>',
        '<script src="/portal/asset-submissions.js" defer></script>',
        '<script src="/portal/asset-production.js" defer></script>',
    )
    for script in scripts:
        if script not in html:
            html = html.replace(marker, f"  {script}\n{marker}", 1)
    return HTMLResponse(html, headers=_SECURITY_HEADERS)


@user_portal_web_router.get("/portal/css/portal_cute.css")
@user_portal_web_router.get("/portal/portal_cute.css")
def user_portal_cute_css() -> FileResponse:
    return _asset("css/portal_cute.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/js/portal.js")
@user_portal_web_router.get("/portal/portal.js")
def user_portal_cute_js() -> FileResponse:
    return _asset("js/portal.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/app.js")
def user_portal_script() -> FileResponse:
    return _asset("app.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/phase1.js")
def user_portal_phase1_script() -> FileResponse:
    return _asset("phase1.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/visits.js")
def user_portal_visits_script() -> FileResponse:
    return _asset("visits.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/realtime.js")
def user_portal_realtime_script() -> FileResponse:
    return _asset("realtime.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/asset-submissions.js")
def user_portal_asset_submissions_script() -> FileResponse:
    return _asset("asset-submissions.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/asset-production.js")
def user_portal_asset_production_script() -> FileResponse:
    return _asset("asset-production.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/styles.css")
def user_portal_styles() -> FileResponse:
    return _asset("styles.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/visits.css")
def user_portal_visits_styles() -> FileResponse:
    return _asset("visits.css", "text/css; charset=utf-8")
