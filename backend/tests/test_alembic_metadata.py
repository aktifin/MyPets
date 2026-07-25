"""Alembic 配置与数据库 Model 元数据一致性校验测试。"""

from __future__ import annotations

from pathlib import Path

from mypets_backend.database import Base
from mypets_backend import models  # noqa: F401
from mypets_backend import social_models  # noqa: F401
from mypets_backend import visit_models  # noqa: F401
from mypets_backend import reminder_models  # noqa: F401
from mypets_backend import asset_submission_models  # noqa: F401
from mypets_backend import asset_production_models  # noqa: F401
from mypets_backend import asset_deployment_models  # noqa: F401


def test_alembic_metadata_tables_complete():
    """验证 Base.metadata 包含了所有的应用模型表。"""
    tables = Base.metadata.tables
    expected_tables = {
        "accounts",
        "devices",
        "pets",
        "account_pet_relations",
        "conversations",
        "conversation_members",
        "messages",
        "message_receipts",
        "sync_events",
        "pet_templates",
        "pet_template_versions",
        "pet_asset_releases",
        "pet_asset_deployments",
        "admin_audit_logs",
        "pet_growth_logs",
        "pet_personality_scores",
        "pet_interaction_logs",
        "friend_requests",
        "friendships",
        "account_blocks",
        "pet_privacy",
        "caregiver_invitations",
        "pet_visits",
        "reminder_occurrences",
        "user_pet_asset_submissions",
        "pet_asset_production_jobs",
        "pet_asset_production_artifacts",
        "pet_asset_production_reference_images",
        "pet_asset_production_job_logs",
        "pet_asset_deployment_reviews",
        "pet_personal_asset_releases",
        "pet_personal_asset_deployments",
    }
    for expected in expected_tables:
        assert expected in tables, f"表 {expected} 未在 Base.metadata 中声明"


def test_alembic_config_files_exist():
    """验证 alembic.ini 和 alembic/env.py 配置文件就绪。"""
    project_root = Path(__file__).resolve().parent.parent
    ini_file = project_root / "alembic.ini"
    env_file = project_root / "alembic" / "env.py"

    assert ini_file.exists(), "alembic.ini 配置文件不存在"
    assert env_file.exists(), "alembic/env.py 环境脚本不存在"
