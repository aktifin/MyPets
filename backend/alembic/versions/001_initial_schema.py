"""初始 23 张 ORM 表结构的 Alembic 基线迁移脚本。

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-07-25 22:00:00.000000

本迁移脚本定义了数据库包含的所有 23 张表结构基线，支持升级与回滚。
"""

from alembic import op
import sqlalchemy as sa

from mypets_backend.database import Base
from mypets_backend.models import *  # 导入所有定义模型
from mypets_backend.social_models import *
from mypets_backend.reminder_models import *
from mypets_backend.visit_models import *
from mypets_backend.asset_submission_models import *
from mypets_backend.asset_production_models import *
from mypets_backend.asset_deployment_models import *
from mypets_backend.user_portal_models import *


# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """创建所有基线 ORM 数据表。"""
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    """撤销并删除所有基线 ORM 数据表。"""
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
