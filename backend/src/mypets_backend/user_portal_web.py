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
    if "portal_cute.css" not in html:
        html = html.replace(
            '<link rel="stylesheet" href="/portal/styles.css">',
            '<link rel="stylesheet" href="/portal/css/portal_cute.css">\n'
            '  <link rel="stylesheet" href="/portal/styles.css">',
            1,
        )
    for stylesheet in (
        '<link rel="stylesheet" href="/portal/customer-experience.css">',
        '<link rel="stylesheet" href="/portal/daily-care-experience.css">',
        '<link rel="stylesheet" href="/portal/proactive-care-experience.css">',
        '<link rel="stylesheet" href="/portal/growth-experience.css">',
        '<link rel="stylesheet" href="/portal/pending-items-experience.css">',
        '<link rel="stylesheet" href="/portal/multi-pet-overview.css">',
        '<link rel="stylesheet" href="/portal/customer-actions-experience.css">',
        '<link rel="stylesheet" href="/portal/customer-history-experience.css">',
        '<link rel="stylesheet" href="/portal/message-efficiency-experience.css">',
    ):
        if stylesheet not in html:
            html = html.replace("</head>", f"  {stylesheet}\n</head>", 1)
    if 'id="section-pet-status"' not in html:
        html = html.replace(
            "</body>",
            '  <div id="section-pet-status" hidden></div>\n'
            '  <div id="section-personality" hidden></div>\n'
            "</body>",
            1,
        )
    marker = "</head>"
    scripts = (
        '<script src="/portal/realtime.js" defer></script>',
        '<script src="/portal/phase1-bootstrap.js" defer></script>',
        '<script src="/portal/asset-submissions.js" defer></script>',
        '<script src="/portal/asset-production.js" defer></script>',
        '<script src="/portal/customer-experience.js" defer></script>',
        '<script src="/portal/daily-care-experience.js" defer></script>',
        '<script src="/portal/proactive-care-experience.js" defer></script>',
        '<script src="/portal/growth-experience.js" defer></script>',
        '<script src="/portal/pending-items-experience.js" defer></script>',
        '<script src="/portal/multi-pet-overview.js" defer></script>',
        '<script src="/portal/customer-actions-experience.js" defer></script>',
        '<script src="/portal/customer-history-experience.js" defer></script>',
        '<script src="/portal/message-efficiency-experience.js" defer></script>',
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


@user_portal_web_router.get("/portal/phase1-bootstrap.js")
def user_portal_phase1_bootstrap_script() -> FileResponse:
    return _asset("phase1-bootstrap.js", "text/javascript; charset=utf-8")


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


@user_portal_web_router.get("/portal/customer-experience.js")
def user_portal_customer_experience_script() -> FileResponse:
    return _asset("customer-experience.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/customer-experience.css")
def user_portal_customer_experience_styles() -> FileResponse:
    return _asset("customer-experience.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/daily-care-experience.js")
def user_portal_daily_care_experience_script() -> FileResponse:
    return _asset("daily-care-experience.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/daily-care-experience.css")
def user_portal_daily_care_experience_styles() -> FileResponse:
    return _asset("daily-care-experience.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/proactive-care-experience.js")
def user_portal_proactive_care_experience_script() -> FileResponse:
    return _asset("proactive-care-experience.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/proactive-care-experience.css")
def user_portal_proactive_care_experience_styles() -> FileResponse:
    return _asset("proactive-care-experience.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/growth-experience.js")
def user_portal_growth_experience_script() -> FileResponse:
    return _asset("growth-experience.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/growth-experience.css")
def user_portal_growth_experience_styles() -> FileResponse:
    return _asset("growth-experience.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/pending-items-experience.js")
def user_portal_pending_items_experience_script() -> FileResponse:
    return _asset("pending-items-experience.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/pending-items-experience.css")
def user_portal_pending_items_experience_styles() -> FileResponse:
    return _asset("pending-items-experience.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/multi-pet-overview.js")
def user_portal_multi_pet_overview_script() -> FileResponse:
    return _asset("multi-pet-overview.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/multi-pet-overview.css")
def user_portal_multi_pet_overview_styles() -> FileResponse:
    return _asset("multi-pet-overview.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/customer-actions-experience.js")
def user_portal_customer_actions_experience_script() -> FileResponse:
    return _asset("customer-actions-experience.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/customer-actions-experience.css")
def user_portal_customer_actions_experience_styles() -> FileResponse:
    return _asset("customer-actions-experience.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/customer-history-experience.js")
def user_portal_customer_history_experience_script() -> FileResponse:
    return _asset("customer-history-experience.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/customer-history-experience.css")
def user_portal_customer_history_experience_styles() -> FileResponse:
    return _asset("customer-history-experience.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/message-efficiency-experience.js")
def user_portal_message_efficiency_script() -> FileResponse:
    return _asset("message-efficiency-experience.js", "text/javascript; charset=utf-8")


@user_portal_web_router.get("/portal/message-efficiency-experience.css")
def user_portal_message_efficiency_styles() -> FileResponse:
    return _asset("message-efficiency-experience.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/styles.css")
def user_portal_styles() -> FileResponse:
    return _asset("styles.css", "text/css; charset=utf-8")


@user_portal_web_router.get("/portal/visits.css")
def user_portal_visits_styles() -> FileResponse:
    return _asset("visits.css", "text/css; charset=utf-8")
