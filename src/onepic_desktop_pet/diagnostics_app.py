"""Final desktop composition with privacy-safe user diagnostics."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import QFileDialog

from .config import user_data_dir
from .diagnostics import (
    configure_logging,
    diagnostic_summary_text,
    export_diagnostic_bundle,
)
from .diagnostics_dialog import DiagnosticsDialog
from .party_app import PartyApplication


class DiagnosticsApplication(PartyApplication):
    """Add one diagnostics window without adding another cloud or pet runtime."""

    def __init__(self, *args, **kwargs) -> None:
        self._diagnostics_dialog: DiagnosticsDialog | None = None
        super().__init__(*args, **kwargs)

        menu = self.system_tray_menu.menu
        anchor = self.system_tray_menu.quit_action
        menu.insertSeparator(anchor)
        self.diagnostics_action = QAction("帮助与诊断…", menu)
        self.diagnostics_action.triggered.connect(self.open_diagnostics_dialog)
        menu.insertAction(anchor, self.diagnostics_action)

    def open_diagnostics_dialog(self) -> None:
        if self._diagnostics_dialog is None:
            dialog = DiagnosticsDialog()
            dialog.refresh_requested.connect(self._refresh_diagnostics_dialog)
            dialog.export_requested.connect(self._export_diagnostics)
            dialog.open_folder_requested.connect(self._open_user_data_folder)
            self._diagnostics_dialog = dialog
        self._refresh_diagnostics_dialog()
        self._diagnostics_dialog.show()
        self._diagnostics_dialog.raise_()
        self._diagnostics_dialog.activateWindow()

    def _refresh_diagnostics_dialog(self) -> None:
        if self._diagnostics_dialog is None:
            return
        self._diagnostics_dialog.set_summary(diagnostic_summary_text(self))
        self._diagnostics_dialog.set_status("诊断信息已刷新。")

    def _open_user_data_folder(self) -> None:
        path = user_data_dir()
        path.mkdir(parents=True, exist_ok=True)
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        if self._diagnostics_dialog is not None:
            self._diagnostics_dialog.set_status(
                "已打开用户数据目录。" if opened else "无法打开用户数据目录。",
                error=not opened,
            )

    def _export_diagnostics(self) -> None:
        desktop = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DesktopLocation
        )
        base = Path(desktop) if desktop else Path.home()
        suggested = base / f"mypets-diagnostics-{datetime.now():%Y%m%d-%H%M%S}.zip"
        filename, _selected_filter = QFileDialog.getSaveFileName(
            self._diagnostics_dialog,
            "导出 MyPets 诊断包",
            str(suggested),
            "ZIP 压缩包 (*.zip)",
        )
        if not filename:
            return
        try:
            target = export_diagnostic_bundle(self, Path(filename))
        except OSError as exc:
            logging.getLogger("mypets.diagnostics").exception("Diagnostic export failed")
            if self._diagnostics_dialog is not None:
                self._diagnostics_dialog.set_status(f"导出失败：{exc}", error=True)
            return
        logging.getLogger("mypets.diagnostics").info("Diagnostic bundle exported to %s", target)
        if self._diagnostics_dialog is not None:
            self._diagnostics_dialog.set_status(f"诊断包已导出：{target}")

    def quit(self) -> None:
        if self._quitting:
            return
        if self._diagnostics_dialog is not None:
            self._diagnostics_dialog.close()
        super().quit()


def run(smoke_test_ms: int | None = None) -> int:
    configure_logging()
    return DiagnosticsApplication().start(smoke_test_ms=smoke_test_ms)
