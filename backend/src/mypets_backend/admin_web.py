"""Static administrator console routes with restrictive browser security headers."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse

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


def _path(name: str) -> Path:
    path = (_WEB_ROOT / name).resolve()
    if not str(path).startswith(str(_WEB_ROOT.resolve())) or not path.is_file():
        raise HTTPException(status_code=404, detail="管理台资源不存在")
    return path


def _asset(name: str, media_type: str) -> FileResponse:
    return FileResponse(_path(name), media_type=media_type, headers=_SECURITY_HEADERS)


@admin_web_router.get("/admin")
@admin_web_router.get("/admin/")
def admin_console() -> HTMLResponse:
    html = _path("index.html").read_text(encoding="utf-8")
    marker = "</body>"
    scripts = (
        '<script src="/admin/asset-submissions.js" defer></script>',
        '<script src="/admin/asset-production.js" defer></script>',
        '<script src="/admin/governance-deployment.js" defer></script>',
    )
    for script in scripts:
        if script not in html:
            html = html.replace(marker, f"  {script}\n{marker}", 1)
    return HTMLResponse(html, headers=_SECURITY_HEADERS)


@admin_web_router.get("/admin/css/admin_cute.css")
@admin_web_router.get("/admin/admin_cute.css")
def admin_cute_css() -> FileResponse:
    return _asset("css/admin_cute.css", "text/css; charset=utf-8")


@admin_web_router.get("/admin/app.js")
def admin_console_script() -> FileResponse:
    return _asset("app.js", "text/javascript; charset=utf-8")


@admin_web_router.get("/admin/asset-submissions.js")
def admin_asset_submission_script() -> FileResponse:
    return _asset("asset-submissions.js", "text/javascript; charset=utf-8")


@admin_web_router.get("/admin/asset-production.js")
def admin_asset_production_script() -> FileResponse:
    return _asset("asset-production.js", "text/javascript; charset=utf-8")


@admin_web_router.get("/admin/governance-deployment.js")
def admin_governance_deployment_script() -> FileResponse:
    return _asset("governance-deployment.js", "text/javascript; charset=utf-8")


@admin_web_router.get("/admin/styles.css")
def admin_console_styles() -> FileResponse:
    return _asset("styles.css", "text/css; charset=utf-8")
