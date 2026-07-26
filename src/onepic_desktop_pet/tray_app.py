"""Default desktop composition root with the optimized system tray menu."""

from __future__ import annotations

from .tray_menu import install_system_tray_menu
from .visit_app import VisitDesktopPetApplication


class TrayDesktopPetApplication(VisitDesktopPetApplication):
    """Install the unified tray menu after all feature layers register their actions."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        install_system_tray_menu(self)


def run(smoke_test_ms: int | None = None) -> int:
    return TrayDesktopPetApplication().start(smoke_test_ms=smoke_test_ms)
