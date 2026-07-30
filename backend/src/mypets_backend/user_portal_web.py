"""Static user portal routes with one explicit asset manifest and restrictive headers."""

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

_ASSETS: dict[str, tuple[str, str]] = {
    "app.js": ("app.js", "text/javascript; charset=utf-8"),
    "phase1.js": ("phase1.js", "text/javascript; charset=utf-8"),
    "phase1-bootstrap.js": ("phase1-bootstrap.js", "text/javascript; charset=utf-8"),
    "visits.js": ("visits.js", "text/javascript; charset=utf-8"),
    "realtime.js": ("realtime.js", "text/javascript; charset=utf-8"),
    "portal-runtime.js": ("portal-runtime.js", "text/javascript; charset=utf-8"),
    "portal-ui.js": ("portal-ui.js", "text/javascript; charset=utf-8"),
    "portal-bootstrap.js": ("portal-bootstrap.js", "text/javascript; charset=utf-8"),
    "asset-submissions.js": ("asset-submissions.js", "text/javascript; charset=utf-8"),
    "asset-production.js": ("asset-production.js", "text/javascript; charset=utf-8"),
    "customer-experience.js": ("customer-experience.js", "text/javascript; charset=utf-8"),
    "daily-care-experience.js": ("daily-care-experience.js", "text/javascript; charset=utf-8"),
    "proactive-care-experience.js": ("proactive-care-experience.js", "text/javascript; charset=utf-8"),
    "growth-experience.js": ("growth-experience.js", "text/javascript; charset=utf-8"),
    "pending-items-experience.js": ("pending-items-experience.js", "text/javascript; charset=utf-8"),
    "multi-pet-overview.js": ("multi-pet-overview.js", "text/javascript; charset=utf-8"),
    "customer-actions-experience.js": (
        "customer-actions-experience.js",
        "text/javascript; charset=utf-8",
    ),
    "customer-history-experience.js": (
        "customer-history-experience.js",
        "text/javascript; charset=utf-8",
    ),
    "message-efficiency-experience.js": (
        "message-efficiency-experience.js",
        "text/javascript; charset=utf-8",
    ),
    "party-experience.js": ("party-experience.js", "text/javascript; charset=utf-8"),
    "party-pending-experience.js": (
        "party-pending-experience.js",
        "text/javascript; charset=utf-8",
    ),
    "device-self-service.js": ("device-self-service.js", "text/javascript; charset=utf-8"),
    "portal.js": ("js/portal.js", "text/javascript; charset=utf-8"),
    "js/portal.js": ("js/portal.js", "text/javascript; charset=utf-8"),
    "styles.css": ("styles.css", "text/css; charset=utf-8"),
    "visits.css": ("visits.css", "text/css; charset=utf-8"),
    "portal-runtime.css": ("portal-runtime.css", "text/css; charset=utf-8"),
    "portal-ui.css": ("portal-ui.css", "text/css; charset=utf-8"),
    "customer-experience.css": ("customer-experience.css", "text/css; charset=utf-8"),
    "daily-care-experience.css": ("daily-care-experience.css", "text/css; charset=utf-8"),
    "proactive-care-experience.css": (
        "proactive-care-experience.css",
        "text/css; charset=utf-8",
    ),
    "growth-experience.css": ("growth-experience.css", "text/css; charset=utf-8"),
    "pending-items-experience.css": (
        "pending-items-experience.css",
        "text/css; charset=utf-8",
    ),
    "multi-pet-overview.css": ("multi-pet-overview.css", "text/css; charset=utf-8"),
    "customer-actions-experience.css": (
        "customer-actions-experience.css",
        "text/css; charset=utf-8",
    ),
    "customer-history-experience.css": (
        "customer-history-experience.css",
        "text/css; charset=utf-8",
    ),
    "message-efficiency-experience.css": (
        "message-efficiency-experience.css",
        "text/css; charset=utf-8",
    ),
    "party-experience.css": ("party-experience.css", "text/css; charset=utf-8"),
    "device-self-service.css": ("device-self-service.css", "text/css; charset=utf-8"),
    "portal_cute.css": ("css/portal_cute.css", "text/css; charset=utf-8"),
    "css/portal_cute.css": ("css/portal_cute.css", "text/css; charset=utf-8"),
}

_STYLESHEETS = (
    "portal-ui.css",
    "customer-experience.css",
    "daily-care-experience.css",
    "proactive-care-experience.css",
    "growth-experience.css",
    "pending-items-experience.css",
    "multi-pet-overview.css",
    "customer-actions-experience.css",
    "customer-history-experience.css",
    "message-efficiency-experience.css",
    "party-experience.css",
    "device-self-service.css",
)

_EXTENSION_SCRIPTS = (
    "portal-ui.js",
    "realtime.js",
    "asset-submissions.js",
    "asset-production.js",
    "customer-experience.js",
    "daily-care-experience.js",
    "proactive-care-experience.js",
    "growth-experience.js",
    "pending-items-experience.js",
    "multi-pet-overview.js",
    "customer-actions-experience.js",
    "customer-history-experience.js",
    "message-efficiency-experience.js",
    "party-experience.js",
    "party-pending-experience.js",
    "device-self-service.js",
    "portal-bootstrap.js",
)


def _path(name: str) -> Path:
    path = (_WEB_ROOT / name).resolve()
    if not str(path).startswith(str(_WEB_ROOT.resolve())) or not path.is_file():
        raise HTTPException(status_code=404, detail="用户门户资源不存在")
    return path


def _asset(name: str, media_type: str) -> FileResponse:
    return FileResponse(_path(name), media_type=media_type, headers=_SECURITY_HEADERS)


def _inject_before(html: str, marker: str, fragment: str) -> str:
    return html if fragment in html else html.replace(marker, f"{fragment}\n{marker}", 1)


@user_portal_web_router.get("/portal")
@user_portal_web_router.get("/portal/")
def user_portal() -> HTMLResponse:
    html = _path("index.html").read_text(encoding="utf-8")
    if "MyPets 用户中心" not in html:
        html = html.replace("</title>", "</title><!-- MyPets 用户中心 -->", 1)

    base_style = '<link rel="stylesheet" href="/portal/styles.css">'
    if "/portal/css/portal_cute.css" not in html:
        html = html.replace(
            base_style,
            '<link rel="stylesheet" href="/portal/css/portal_cute.css">\n'
            '  <link rel="stylesheet" href="/portal/portal-runtime.css">\n'
            f"  {base_style}",
            1,
        )
    elif "/portal/portal-runtime.css" not in html:
        html = html.replace(
            base_style,
            '<link rel="stylesheet" href="/portal/portal-runtime.css">\n'
            f"  {base_style}",
            1,
        )

    app_script = '<script src="/portal/app.js" defer></script>'
    runtime_script = '<script src="/portal/portal-runtime.js" defer></script>'
    if runtime_script not in html:
        html = html.replace(app_script, f"{runtime_script}\n  {app_script}", 1)

    for name in _STYLESHEETS:
        html = _inject_before(
            html,
            "</head>",
            f'  <link rel="stylesheet" href="/portal/{name}">',
        )

    if 'id="section-pet-status"' not in html:
        html = html.replace(
            "</body>",
            '  <div id="section-pet-status" hidden></div>\n'
            '  <div id="section-personality" hidden></div>\n'
            "</body>",
            1,
        )

    for name in _EXTENSION_SCRIPTS:
        html = _inject_before(
            html,
            "</head>",
            f'  <script src="/portal/{name}" defer></script>',
        )
    return HTMLResponse(html, headers=_SECURITY_HEADERS)


@user_portal_web_router.get("/portal/{asset_path:path}")
def user_portal_asset(asset_path: str) -> FileResponse:
    asset = _ASSETS.get(asset_path)
    if asset is None:
        raise HTTPException(status_code=404, detail="用户门户资源不存在")
    path, media_type = asset
    return _asset(path, media_type)
