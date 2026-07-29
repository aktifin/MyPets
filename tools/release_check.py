"""Fail fast when release metadata, documentation, or packaging contracts drift."""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_PATTERN = re.compile(r"^\d+\.\d+\.\d+a\d+$")
CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8-sig")


def _toml_version(path: str) -> str:
    with (ROOT / path).open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])


def _python_constant(path: str, name: str) -> str:
    tree = ast.parse(_read(path), filename=path)
    for statement in tree.body:
        if not isinstance(statement, ast.Assign):
            continue
        if len(statement.targets) != 1 or not isinstance(statement.targets[0], ast.Name):
            continue
        if statement.targets[0].id == name and isinstance(statement.value, ast.Constant):
            return str(statement.value.value)
    raise ValueError(f"{path} 未定义常量 {name}")


def collect_errors() -> list[str]:
    errors: list[str] = []
    required = (
        "VERSION",
        "README.md",
        "LICENSE",
        "docs/普通用户安装使用指南.md",
        "docs/发布检查清单.md",
        "scripts/start_local.ps1",
        "scripts/package_release.ps1",
        "src/onepic_desktop_pet/release.py",
        "backend/src/mypets_backend/release.py",
    )
    for path in required:
        if not (ROOT / path).is_file():
            errors.append(f"缺少发布必需文件：{path}")

    if errors:
        return errors

    version = _read("VERSION").strip()
    if not VERSION_PATTERN.fullmatch(version):
        errors.append(f"VERSION 必须使用 PEP 440 Alpha 格式，例如 0.3.0a1；当前为 {version!r}")

    values = {
        "VERSION": version,
        "desktop pyproject": _toml_version("pyproject.toml"),
        "backend pyproject": _toml_version("backend/pyproject.toml"),
        "desktop release.py": _python_constant(
            "src/onepic_desktop_pet/release.py", "APP_VERSION"
        ),
        "backend release.py": _python_constant(
            "backend/src/mypets_backend/release.py", "APP_VERSION"
        ),
    }
    for source, value in values.items():
        if value != version:
            errors.append(f"版本不一致：{source}={value!r}，VERSION={version!r}")

    documents = (
        "README.md",
        "docs/普通用户安装使用指南.md",
        "docs/发布检查清单.md",
        "implementation_plan.md",
    )
    for path in documents:
        text = _read(path)
        for marker in CONFLICT_MARKERS:
            if marker in text:
                errors.append(f"{path} 仍包含合并冲突标记 {marker}")
        if path != "implementation_plan.md" and version not in text:
            errors.append(f"{path} 未声明当前版本 {version}")

    desktop_metadata = tomllib.loads(_read("pyproject.toml"))["project"]
    if "agent" in str(desktop_metadata.get("description", "")).lower():
        errors.append("桌面包描述仍包含已移除的 Agent 产品定位")

    backend_main = _read("backend/src/mypets_backend/main.py")
    if "version=APP_VERSION" not in backend_main:
        errors.append("FastAPI 应用未使用统一 APP_VERSION")
    if '"version": APP_VERSION' not in backend_main:
        errors.append("健康检查未返回统一版本")
    if '"channel": RELEASE_CHANNEL' not in backend_main:
        errors.append("健康检查未返回发布通道")

    package_script = _read("scripts/package_release.ps1")
    for required_text in (
        "MyPets-Desktop-$version-windows-x64",
        "release_check.py",
        "Get-FileHash",
        "普通用户安装使用指南.md",
    ):
        if required_text not in package_script:
            errors.append(f"发布打包脚本缺少契约：{required_text}")

    local_script = _read("scripts/start_local.ps1")
    for required_text in ("/health", "/portal", "uvicorn", "Stop-Process"):
        if required_text not in local_script:
            errors.append(f"一键本地启动脚本缺少契约：{required_text}")

    return errors


def main() -> int:
    errors = collect_errors()
    if errors:
        print("MyPets 发布检查失败：", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"MyPets release metadata OK: {_read('VERSION').strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
