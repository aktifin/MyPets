from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

from onepic_desktop_pet.diagnostics import (
    build_diagnostic_snapshot,
    diagnostic_summary_text,
    export_diagnostic_bundle,
)
from onepic_desktop_pet.release import APP_NAME, APP_VERSION, RELEASE_CHANNEL


class _Registry:
    def list_pets(self):
        return [object(), object()]


class _DummyApp:
    def __init__(self) -> None:
        self.settings = SimpleNamespace(
            display_height=220,
            always_on_top=True,
            edge_dock_enabled=True,
            edge_side="right",
            cloud_base_url="https://pets.example.invalid",
            cloud_sync_enabled=True,
            cloud_sync_interval_ms=15000,
            proactive_care_enabled=True,
            proactive_quiet_hours_enabled=True,
            proactive_quiet_start="22:00",
            proactive_quiet_end="08:00",
            multi_pet_layout_enabled=True,
            desktop_experience_version=1,
            device_public_id="private-device-public-id",
            access_token="private-access-token",
        )
        self.cloud_session = SimpleNamespace(
            state=SimpleNamespace(value="connected"),
            identity=SimpleNamespace(
                username="diagnostic_owner",
                display_name="诊断用户",
                account_id="private-account-id",
                device_secret="private-device-secret",
            ),
        )
        self.active_pet = SimpleNamespace(
            identity=SimpleNamespace(name="团子", primary_owner_account_id="private-account-id"),
            presence=SimpleNamespace(value="home"),
            stats=SimpleNamespace(growth_level=7),
        )
        self.pet_registry = _Registry()


def test_diagnostic_snapshot_contains_release_and_runtime_without_credentials(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    snapshot = build_diagnostic_snapshot(_DummyApp())
    serialized = json.dumps(snapshot, ensure_ascii=False)

    assert snapshot["application"] == {
        "name": APP_NAME,
        "version": APP_VERSION,
        "channel": RELEASE_CHANNEL,
    }
    assert snapshot["cloud"]["state"] == "connected"
    assert snapshot["desktop"]["pet_count"] == 2
    assert snapshot["desktop"]["active_pet"]["name"] == "团子"
    assert "private-access-token" not in serialized
    assert "private-device-secret" not in serialized
    assert "private-device-public-id" not in serialized
    assert "private-account-id" not in serialized


def test_diagnostic_bundle_only_contains_snapshot_readme_and_bounded_logs(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    log_dir = tmp_path / "OnePicDesktopPet" / "logs"
    log_dir.mkdir(parents=True)
    (log_dir / "mypets.log").write_text("safe diagnostic log\n", encoding="utf-8")
    (log_dir / "other-secret.txt").write_text("must not be exported", encoding="utf-8")

    target = export_diagnostic_bundle(_DummyApp(), tmp_path / "support")
    assert target.name == "support.zip"

    with ZipFile(target) as archive:
        names = set(archive.namelist())
        assert names == {"diagnostics.json", "README.txt", "logs/mypets.log"}
        diagnostics = archive.read("diagnostics.json").decode("utf-8")
        assert "private-access-token" not in diagnostics
        assert "private-device-secret" not in diagnostics
        assert "must not be exported" not in diagnostics
        assert archive.read("logs/mypets.log").decode("utf-8") == "safe diagnostic log\n"


def test_diagnostic_summary_is_user_readable(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    summary = diagnostic_summary_text(_DummyApp())

    assert f"{APP_NAME} {APP_VERSION}" in summary
    assert "云端状态：connected" in summary
    assert "账户：诊断用户" in summary
    assert "宠物：2 只 · 当前：团子" in summary
    assert "不包含密码" in summary


def test_main_uses_the_diagnostics_composition_root() -> None:
    source = Path("main.py").read_text(encoding="utf-8")
    app_source = Path("src/onepic_desktop_pet/diagnostics_app.py").read_text(encoding="utf-8")

    assert "from onepic_desktop_pet.diagnostics_app import run" in source
    assert "class DiagnosticsApplication(PartyApplication)" in app_source
    assert 'QAction("帮助与诊断…"' in app_source
    assert "export_diagnostic_bundle" in app_source
    assert "QDesktopServices.openUrl" in app_source
    assert "credential" not in app_source.lower()
