# MyPets 数据库迁移与 PostgreSQL 部署

MyPets 后端使用 Alembic 管理正式数据库结构。当前版本链为：

```text
001_initial_schema
└── 002_asset_revocation_ack
    └── 003_rights_evidence_history
        └── 004_revocation_follow_up (head)
```

生产环境不得依赖应用启动时的 `Base.metadata.create_all`。

## 一、Revision 说明

- `001_initial_schema`：冻结 35 张基础业务表的显式 DDL；
- `002_asset_revocation_ack`：新增设备撤销清理回执表，业务表增至 36 张；
- `003_rights_evidence_history`：扩展版权有效期和复核字段，并新增证据附件与状态历史表，业务表增至 38 张；
- `004_revocation_follow_up`：新增设备撤销人工跟进历史表，业务表增至 39 张。

第四个 Revision 新增：

```text
pet_asset_revocation_follow_ups
```

该表保存 right、Release、宠物、账户、设备、可选回执、处理状态、跟进说明、操作人和时间。每次人工处理都追加新记录，不覆盖客户端原始回执，也不覆盖既有跟进历史。

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
004_revocation_follow_up (head)
```

`alembic check` 必须确认 SQLAlchemy Metadata 不存在未提交漂移。

## 三、生产升级

推荐顺序：

1. 同时备份数据库和对象存储；
2. 停止写入或进入维护窗口；
3. 执行 `alembic upgrade head`；
4. 执行 `alembic current` 和 `alembic check`；
5. 启动新版本应用；
6. 验证登录、宠物、消息、提醒、版权证据、D3 发布、设备撤销回执和人工跟进；
7. 恢复流量。

生产环境必须配置：

```bash
export MYPETS_ENVIRONMENT=production
export MYPETS_JWT_SECRET='replace-with-a-long-random-secret'
export MYPETS_CREATE_SCHEMA_ON_START=0
```

## 四、增量升级

从任意旧 Revision 直接执行：

```bash
cd backend
alembic current
alembic upgrade head
alembic current
alembic check
```

需要逐级验证时：

```bash
alembic upgrade 002_asset_revocation_ack
alembic upgrade 003_rights_evidence_history
alembic upgrade 004_revocation_follow_up
```

第四个 Revision 只新增一张跟进历史表和两个索引，不修改设备回执、版权主表和对象存储。高数据量环境仍应在预发布数据库评估 PostgreSQL DDL 锁和索引创建时间。

## 五、单步回退

从 004 回退到 003：

```bash
alembic downgrade 003_rights_evidence_history
```

该操作只删除设备撤销人工跟进历史，不删除客户端回执、版权记录、专属 Release 或设备数据。生产执行前必须确认跟进记录已经导出或可丢弃。

从 003 回退到 002：

```bash
alembic downgrade 002_asset_revocation_ack
```

该操作会删除证据附件元数据、版权状态历史以及版权有效期和复核字段。对象存储中的证据正文不会由 Alembic 自动删除，必须按同一备份恢复点协调处理。

从 002 回退到 001：

```bash
alembic downgrade 001_initial_schema
```

该操作删除设备撤销清理回执表。

生产环境不得将 `downgrade base` 作为常规回滚方式，应优先恢复升级前数据库与对象存储的一致快照。

## 六、接管历史 create_all 数据库

历史数据库必须先与当前 SQLAlchemy Metadata 完整比对：

```bash
cd backend
python scripts/check_existing_schema.py
```

工具检查表、字段、类型、可空性、默认值、外键、唯一约束和索引，当前应覆盖 39 张业务表。只有输出：

```text
Existing database schema matches MyPets metadata.
```

才允许执行：

```bash
alembic stamp head
alembic current
alembic check
```

已经标记为旧 Revision 的数据库不得直接 stamp 到 head，必须实际执行增量升级。

## 七、对象存储一致性

数据库备份和对象存储备份必须使用同一恢复点。重点对象前缀包括：

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
- 已撤销或过期授权不能继续分发专属素材；
- 撤销回执和人工跟进能够按设备正确关联；
- 数据库回滚后不存在错误引用。

## 八、新增迁移要求

模型变化后可使用：

```bash
alembic revision --autogenerate -m "describe schema change"
```

生成结果必须人工审核数据回填、非空列顺序、SQLite batch migration、PostgreSQL 锁和索引、外键删除策略、downgrade 数据损失以及数据库与对象存储的一致性。

## 九、持续集成

数据库 CI 对 SQLite 与 PostgreSQL 16 验证：

```text
base → 001 → 002 → 003 → 004(head)
004 → 003 → 002 → 001 → base → head
```

并检查：

- head 为 `004_revocation_follow_up`；
- head 下存在 39 张业务表；
- 回退到 003 后人工跟进表消失；
- 回退到 002 后证据、历史表及新增列消失；
- 回退到 001 后设备回执表消失；
- 历史 `create_all` 数据库可安全比对和接管；
- Alembic 与 SQLAlchemy Metadata 无漂移。

数据库迁移、Linux/Windows 测试、Web JavaScript 和 Qt 冒烟必须全部通过后才能合并。
