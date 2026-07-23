"""管理员与素材制作者使用的宠物 Manifest 校验命令。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from onepic_desktop_pet.appearance import (  # noqa: E402
    load_pet_manifest,
    validate_manifest_assets,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验宠物视觉身份、动作降级和跨端素材 Manifest。",
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=ROOT / "assets" / "pet" / "manifest.json",
        help="需要校验的 manifest.json 路径",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    path = args.manifest.resolve()
    try:
        manifest = load_pet_manifest(path)
    except ValueError as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 2

    problems = validate_manifest_assets(path, manifest)
    print(f"Manifest: {path}")
    print(f"Schema: {manifest.schema_version}")
    print(f"Template: {manifest.template_code or '(legacy)'}")
    print(f"Identity: {manifest.identity_version}")
    print(f"Assets: {manifest.asset_version}")
    print(f"Actions: {len(manifest.animations)}")
    enabled_capabilities = sorted(
        name for name, enabled in manifest.capabilities.items() if enabled
    )
    print("Capabilities: " + (", ".join(enabled_capabilities) or "(none)"))

    if problems:
        for problem in problems:
            print(f"[FAIL] {problem}", file=sys.stderr)
        return 1
    print("[OK] Manifest 结构和素材路径均通过校验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
