"""Administrator CLI for validating frame and spritesheet pet runtime manifests."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from onepic_desktop_pet.pet_assets import load_pet_asset_manifest  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="校验宠物身份版本、动作降级、精灵表坐标、路径和素材完整性。",
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        type=Path,
        default=ROOT / "assets" / "pet" / "manifest.json",
        help="需要校验的运行时 manifest.json 路径",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    path = build_parser().parse_args(argv).manifest.resolve()
    try:
        manifest = load_pet_asset_manifest(path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"[FAIL] {exc}", file=sys.stderr)
        return 1

    renderer = "spritesheet" if manifest.spritesheet is not None else "frames"
    print(f"Manifest: {manifest.path}")
    print(f"Template: {manifest.identity.template_id}")
    print(f"Identity: {manifest.identity.identity_version}")
    print(f"Assets: {manifest.identity.asset_version}")
    print(f"Renderer: {renderer}")
    print(f"Runtime actions: {len(manifest.animations)}")
    print(f"Referenced files: {len(manifest.referenced_paths())}")
    if manifest.local_pet is not None:
        print(f"Bundled pet: {manifest.local_pet.name} ({manifest.local_pet.pet_id})")
    print("[OK] Manifest、动作降级、路径和素材均通过校验")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
