# MyPets 数据库迁移与 PostgreSQL 部署

MyPets 后端使用 Alembic 管理正式数据库结构。当前版本链为：

```text
001_initial_schema
└── 002_asset_revocation_ack
    └── 003_rights_evidence_history (head)
```

生产环境不得依赖应用启动时的 `Base.metadata.create_all`。

## 一、Revision 说明

- `001_initial_schema`：冻结 35 张基础业务表的显式 DDL；
- `002_asset_revocation_ack`：新增设备撤销清理回执表，业务表增至 36 张；
- `003_rights_evidence_history`：扩展版权有效期和复核字段，并新增证据附件与状态历史两张表，业务表增至 38 张。

第三个 Revision 对 `pet_asset_rights` 增加：

```text
valid_from
valid_until
review_comment
verified_at
revoked_at
```

并新增：

```text
pet_asset_right_evidence
pet_asset_right_history
```

证据文件正文不保存在数据库，而是写入对象存储；数据库只保存对象键、文件名、媒体类型、SHA-256、大小、上传人和时间。

## 二、新建数据库

```bash
cd backend
python -m pip install -e ".[dev]"
export MYPETS_DATABASE_URL='postgresql+psycopg://mypets:strong-password@db-host:5432/mypets'
alembic upgrade head
alembic current
alembic check
```

当前 `alembic current` 应显示：

```text
003_rights_evidence_history (head)
```

模型漂移检查必须无新增操作。

## 三、生产升级

推荐顺序：

1. 同时备份数据库和对象存储；
2. 停止写入或进入维护窗口；
3. 执行 `alembic upgrade head`；
4. 执行 `alembic current` 和 `alembic check`；
5. 启动新版本应用；
6. 验证登录、宠物、消息、提醒、版权证据上传、历史查询、D3 发布和撤销回执；
7. 恢复流量。

生产环境必须配置：

```bash
export MYPETS_ENVIRONMENT=production
export MYPETS_JWT_SECRET='replace-with-a-long-random-secret'
export MYPETS_CREATE_SCHEMA_ON_START=0
```

## 四、增量升级

### 从 001 升级

```bash
alembic upgrade 002_asset_revocation_ack
alembic upgrade 003_rights_evidence_history
alembic check
```

### 从 002 升级

```bash
alembic current
alembic upgrade 003_rights_evidence_history
alembic current
alembic check
```

第三个 Revision 会修改版权主表并创建两张新表。高数据量环境应在预发布数据库评估 `batch_alter_table`、PostgreSQL DDL 锁和索引创建时间。

## 五、单步回退

从 003 回退到 002：

```bash
alembic downgrade 002_asset_revocation_ack
```

该操作会删除：

- 全部证据附件元数据；
- 全部版权状态历史；
- 版权有效期、复核意见和关键时间字段。

对象存储中的证据正文不会被 Alembic 自动删除，回退前后必须由运维按数据库备份点协调对象存储恢复或清理，避免孤儿对象和元数据缺失。

从 002 回退到 001：

```bash
alembic downgrade 001_initial_schema
```

该操作删除设备撤销清理回执表。

生产环境不得将 `downgrade base` 作为常规回滚手段，应优先恢复升级前数据库与对象存储的一致快照。

## 六、接管历史 create_all 数据库

历史数据库必须先确认与当前 SQLAlchemy Metadata 完全一致：

```bash
cd backend
python scripts/check_existing_schema.py
```

工具会检查表、字段、类型、可空性、默认值、外键、唯一约束和索引，当前应覆盖 38 张业务表。

只有输出以下信息时才允许执行：

```text
Existing database schema matches MyPets metadata.
```

随后：

```bash
alembic stamp head
alembic current
alembic check
```

已经标记为旧 Revision 的数据库不能直接 stamp 到 head，应实际执行增量升级。

## 七、对象存储一致性

数据库备份与对象存储备份必须使用同一恢复点。重点对象前缀包括：

```text
submissions/
production/
releases/
governance/rights/
```

恢复演练至少验证：

- 证据元数据引用的对象存在；
- 文件 SHA-256 与数据库一致；
- 受保护下载仍要求管理员令牌；
- 已撤销或过期授权不能分发专属素材；
- 数据库回滚后不存在错误引用。

## 八、新增迁移要求

模型变化后可使用：

```bash
alembic revision --autogenerate -m "describe schema change"
```

生成结果必须人工审核：

- 数据回填与非空列顺序；
- SQLite batch migration；
- PostgreSQL 锁和索引行为；
- 外键删除策略；
- downgrade 的数据损失范围；
- 数据库与对象存储是否需要协同迁移。

## 九、持续集成

数据库 CI 对 SQLite 与 PostgreSQL 16 验证：

```text
base → 001 → 002 → 003(head)
003 → 002 → 001 → base → head
```

并检查：

- head 为 `003_rights_evidence_history`；
- head 下存在 38 张业务表；
- 回退到 002 后证据和历史表及新增列消失；
- 回退到 001 后设备回执表消失；
- 历史 `create_all` 数据库可安全比对和接管；
- Alembic 与 SQLAlchemy Metadata 无漂移。

数据库迁移、Linux/Windows 测试、Web JavaScript 和 Qt 冒烟必须全部通过后才能合并。
