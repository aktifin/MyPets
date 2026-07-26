"""测试桌面宠物配置的合并、范围校验、云端非敏感设置和原子保存行为。"""

import json

from onepic_desktop_pet.config import PetSettings, load_settings, save_settings


def test_load_settings_merges_position_and_user_selected_size(tmp_path) -> None:
    default_path = tmp_path / "default.json"
    override_path = tmp_path / "override.json"
    default_path.write_text(
        json.dumps({"display_height": 280, "movement_step": 3}),
        encoding="utf-8",
    )
    override_path.write_text(
        json.dumps(
            {
                "display_height": 9999,
                "movement_step": 0,
                "start_x": 25,
                "start_y": 40,
                "edge_side": "right",
                "edge_offset_ratio": 0.7,
                "desktop_experience_version": 1,
                "unknown": 1,
            }
        ),
        encoding="utf-8",
    )

    settings = load_settings(default_path, override_path)

    assert settings.display_height == 600
    assert settings.movement_step == 3
    assert settings.start_x == 25
    assert settings.start_y == 40
    assert settings.edge_side == "right"
    assert settings.edge_offset_ratio == 0.7
    assert settings.desktop_experience_version == 1
    assert not hasattr(settings, "unknown")


def test_broken_user_config_falls_back_to_defaults(tmp_path) -> None:
    default_path = tmp_path / "default.json"
    override_path = tmp_path / "override.json"
    default_path.write_text('{"movement_step": 5}', encoding="utf-8")
    override_path.write_text("not-json", encoding="utf-8")
    assert load_settings(default_path, override_path).movement_step == 5


def test_animation_timing_is_limited_to_safe_ranges(tmp_path) -> None:
    default_path = tmp_path / "default.json"
    default_path.write_text(
        json.dumps({"walk_frame_interval_ms": 1, "turn_pause_ms": 9999}),
        encoding="utf-8",
    )
    settings = load_settings(default_path, tmp_path / "missing.json")
    assert settings.walk_frame_interval_ms == 50
    assert settings.turn_pause_ms == 1200


def test_edge_settings_are_limited_to_safe_ranges(tmp_path) -> None:
    default_path = tmp_path / "default.json"
    default_path.write_text(
        json.dumps(
            {
                "edge_snap_distance": 999,
                "edge_hide_delay_ms": 1,
                "edge_animation_ms": -5,
                "edge_visible_ratio": 0.99,
                "edge_side": "bottom",
                "edge_offset_ratio": 2,
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings(default_path, tmp_path / "missing.json")
    assert settings.edge_snap_distance == 120
    assert settings.edge_hide_delay_ms == 100
    assert settings.edge_animation_ms == 0
    assert settings.edge_visible_ratio == 0.80
    assert settings.edge_side == "bottom"
    assert settings.edge_offset_ratio == 1.0


def test_cloud_settings_are_normalized_without_persisting_secrets(tmp_path) -> None:
    default_path = tmp_path / "default.json"
    override_path = tmp_path / "override.json"
    default_path.write_text("{}", encoding="utf-8")
    override_path.write_text(
        json.dumps(
            {
                "cloud_base_url": "https://pets.example.com/api/",
                "cloud_sync_enabled": True,
                "cloud_sync_interval_ms": 1,
                "device_public_id": "desktop-public-id",
                "device_secret": "must-not-load",
                "access_token": "must-not-load",
            }
        ),
        encoding="utf-8",
    )
    settings = load_settings(default_path, override_path)
    assert settings.cloud_base_url == "https://pets.example.com/api"
    assert settings.cloud_sync_enabled is True
    assert settings.cloud_sync_interval_ms == 5000
    assert settings.device_public_id == "desktop-public-id"
    assert not hasattr(settings, "device_secret")
    assert not hasattr(settings, "access_token")


def test_invalid_or_missing_device_id_is_regenerated(tmp_path) -> None:
    default_path = tmp_path / "default.json"
    default_path.write_text(
        json.dumps({"device_public_id": "x", "cloud_base_url": "not-a-url"}),
        encoding="utf-8",
    )
    settings = load_settings(default_path, tmp_path / "missing.json")
    assert len(settings.device_public_id) >= 8
    assert settings.cloud_base_url == "http://127.0.0.1:8000"


def test_default_inactivity_uses_five_and_ten_minutes() -> None:
    settings = PetSettings()
    assert settings.inactive_sit_ms == 300000
    assert settings.inactive_sleep_ms == 600000
    assert settings.desktop_experience_version == 0


def test_save_settings_writes_json_without_credentials(tmp_path) -> None:
    path = tmp_path / "nested" / "settings.json"
    saved = save_settings(
        PetSettings(
            start_x=12,
            start_y=34,
            edge_side="left",
            edge_screen_name="DISPLAY1",
            edge_offset_ratio=0.25,
            cloud_base_url="https://pets.example.com",
            cloud_sync_enabled=True,
            cloud_sync_interval_ms=20000,
            device_public_id="desktop-public-id",
            desktop_experience_version=1,
        ),
        path,
    )
    data = json.loads(saved.read_text(encoding="utf-8"))
    assert data["start_x"] == 12
    assert data["start_y"] == 34
    assert data["display_height"] == 220
    assert data["edge_side"] == "left"
    assert data["edge_screen_name"] == "DISPLAY1"
    assert data["edge_offset_ratio"] == 0.25
    assert data["cloud_base_url"] == "https://pets.example.com"
    assert data["cloud_sync_enabled"] is True
    assert data["cloud_sync_interval_ms"] == 20000
    assert data["device_public_id"] == "desktop-public-id"
    assert data["desktop_experience_version"] == 1
    assert set(data) == {
        "display_height",
        "start_x",
        "start_y",
        "edge_dock_enabled",
        "edge_side",
        "edge_screen_name",
        "edge_offset_ratio",
        "cloud_base_url",
        "cloud_sync_enabled",
        "cloud_sync_interval_ms",
        "device_public_id",
        "desktop_experience_version",
    }
    assert "device_secret" not in data
    assert "access_token" not in data
    assert not path.with_suffix(".json.tmp").exists()
