from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_release_check():
    path = ROOT / "tools" / "release_check.py"
    spec = importlib.util.spec_from_file_location("mypets_release_check", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_metadata_and_documentation_are_consistent() -> None:
    module = _load_release_check()

    assert module.collect_errors() == []


def test_release_scripts_keep_client_and_local_experience_boundaries() -> None:
    package_script = (ROOT / "scripts" / "package_release.ps1").read_text(
        encoding="utf-8-sig"
    )
    local_script = (ROOT / "scripts" / "start_local.ps1").read_text(
        encoding="utf-8-sig"
    )

    assert "MyPets-Desktop-$version-windows-x64" in package_script
    assert "本压缩包仅包含 Windows 桌面客户端" in package_script
    assert "Compress-Archive" in package_script
    assert "Get-FileHash" in package_script

    assert "mypets_backend.main:app" in local_script
    assert "Test-MyPetsHealth" in local_script
    assert "Stop-Process" in local_script
    assert "start_local.ps1" not in local_script.replace(
        '"$PSScriptRoot\\setup_environment.ps1"', ""
    )
