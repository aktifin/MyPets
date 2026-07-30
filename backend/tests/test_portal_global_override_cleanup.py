from __future__ import annotations

import re
from pathlib import Path


STATIC_ROOT = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "mypets_backend"
    / "user_portal_static"
)

# These files are either the authoritative definition layer, the runtime itself,
# or an un-injected compatibility asset retained for old bookmarks/builds.
OVERRIDE_SCAN_EXCLUSIONS = {
    "app.js",
    "portal-runtime.js",
    "phase1-bootstrap.js",
}

GLOBAL_ASSIGNMENT = re.compile(
    r"(?m)^\s*(refreshAll|renderDashboard|renderPortalPhase1|performPhase1Care|logout)\s*="
)
DIRECT_REALTIME_LISTENER = 'window.addEventListener("mypets:realtime-cursor"'


def extension_sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted(STATIC_ROOT.glob("*.js"))
        if path.name not in OVERRIDE_SCAN_EXCLUSIONS
    }


def test_extensions_do_not_replace_authoritative_portal_globals() -> None:
    violations: dict[str, list[str]] = {}
    for name, source in extension_sources().items():
        matches = GLOBAL_ASSIGNMENT.findall(source)
        if matches:
            violations[name] = matches

    assert violations == {}


def test_extensions_use_runtime_realtime_lifecycle() -> None:
    violations = [
        name
        for name, source in extension_sources().items()
        if DIRECT_REALTIME_LISTENER in source
    ]

    assert violations == []


def test_realtime_transport_uses_session_lifecycle_without_entry_wrappers() -> None:
    source = (STATIC_ROOT / "realtime.js").read_text(encoding="utf-8")

    assert 'id: "realtime-transport"' in source
    assert "order: 500" in source
    assert "onRefreshComplete: startRealtime" in source
    assert "onLogout: stopRealtime" in source
    assert 'new CustomEvent("mypets:realtime-cursor"' in source
    assert "refreshVisits" not in source
    assert "originalEnterApp" not in source
    assert "originalLogout" not in source
    assert "enterApp = function" not in source
    assert "logout = function" not in source


def test_final_bootstrap_contains_no_projection_or_background_compatibility() -> None:
    source = (STATIC_ROOT / "portal-bootstrap.js").read_text(encoding="utf-8")

    assert "legacy-render-projection-bridge" not in source
    assert "__mypetsPortalRenderBridgeInstalled" not in source
    assert "renderDashboard =" not in source
    assert "renderPortalPhase1 =" not in source
    assert "setInterval" not in source
    assert "setTimeout" not in source
