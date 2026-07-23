"""宠物形象 Manifest 的兼容、降级和安全校验测试。"""

import pytest

from onepic_desktop_pet.appearance import parse_pet_manifest


def _legacy_manifest() -> dict:
    actions = {
        "idle": ["idle.png"],
        "walk": ["walk-1.png", "walk-2.png"],
        "sit": ["sit.png"],
        "sleep": ["sleep.png"],
        "wave": ["wave.png"],
        "happy": ["happy.png"],
        "shy": ["shy.png"],
        "surprised": ["surprised.png"],
        "annoyed": ["annoyed.png"],
        "sleepy": ["sleepy.png"],
        "curious": ["curious.png"],
        "selfie": ["selfie.png"],
        "drag": ["drag.png"],
    }
    return {"animations": actions}


def test_legacy_manifest_receives_safe_defaults() -> None:
    manifest = parse_pet_manifest(_legacy_manifest())

    assert manifest.schema_version == "1.0"
    assert manifest.identity_version == "1.0.0"
    assert manifest.walk_motion_factors == (1.0, 1.0)
    assert manifest.edge_peek.anchor == "face"


def test_new_action_can_fall_back_to_existing_animation() -> None:
    source = _legacy_manifest()
    source["fallback_actions"] = {"reminder": "wave"}
    manifest = parse_pet_manifest(source)

    assert manifest.animation_paths("reminder") == ("wave.png",)


def test_invalid_walk_curve_is_rejected() -> None:
    source = _legacy_manifest()
    source["walk_motion_factors"] = [1.0]

    with pytest.raises(ValueError, match="走路位移曲线"):
        parse_pet_manifest(source)


def test_edge_peek_ratio_is_validated() -> None:
    source = _legacy_manifest()
    source["appearance"] = {
        "edge_peek": {
            "left_visible_ratio": 0.01,
            "right_visible_ratio": 0.3,
            "anchor": "face",
        }
    }

    with pytest.raises(ValueError, match="边缘可见比例"):
        parse_pet_manifest(source)
