# MyPets 数据库迁移与 PostgreSQL 部署

MyPets 后端从 Revision `001_initial_schema` 起使用 Alembic 管理正式数据库结构。该标识沿用仓库已有基线，避免已经 stamp 的历史数据库失去版本连续性；基线实现已冻结为显式 DDL，不再在迁移执行时调用 `Base.metadata.create_all`。Revision `002_asset_revocation_ack` 新增设备撤销素材清理回执表，用于验证真实增量迁移。生产环境不得依赖应用启动时的自动建表。

## 一、适用范围

- 新建 SQLite 开发数据库；
- 新建 PostgreSQL 测试或生产数据库；
- 将历史上由 `Base.metadata.create_all` 建立的数据库接入 Alembic；
- 从 `001_initial_schema` 增量升级到设备撤销回执版本；
- 发布前检查 SQLAlchemy 模型与数据库结构是否发生未提交漂移；
- 执行升级、单步回退和恢复验证。

桌面端 SQLite 仍然只是可重建缓存和断点续办队列，不纳入服务端 Alembic 迁移链。本文所述数据库是 FastAPI 后端的服务端权威数据库。

## 二、新建数据库

先安装后端及迁移依赖：

```bash
cd backend
python -m pip install -e ".[dev]"
```

配置数据库地址。PostgreSQL 示例：

```bash
export MYPETS_DATABASE_URL='postgresql+psycopg://mypets:strong-password@db-host:5432/mypets'
```

Windows PowerShell：

```powershell
$env:MYPETS_DATABASE_URL = 'postgresql+psycopg://mypets:strong-password@db-host:5432/mypets'
```

执行升级：

```bash
alembic upgrade head
alembic current
alembic check
```

`alembic current` 应显示：

```text
002_asset_revocation_ack (head)
```

`alembic check` 应显示没有新的升级操作。若检测到模型漂移，不得直接启动生产服务，应先生成和评审新的增量 Revision。

## 三、版本链

当前版本链：

```text
001_initial_schema
└── 002_asset_revocation_ack (head)
```

- `001_initial_schema`：冻结 35 张基础业务表的显式 DDL；
- `002_asset_revocation_ack`：新增 `pet_asset_revocation_acknowledgements`，形成 36 张服务端业务表。

第二个 Revision 记录每台设备对版权撤销事件的清理结果，包括版权存证、产物、专属 Release、宠物、账户、设备、清理状态、安全降级状态、客户端处理时间和重试次数。唯一约束为 `right_id + release_id + device_id`，重复回执只更新同一设备记录。

## 四、生产启动要求

生产环境必须设置：

```bash
export MYPETS_ENVIRONMENT=production
export MYPETS_JWT_SECRET='replace-with-a-long-random-secret'
export MYPETS_CREATE_SCHEMA_ON_START=0
```

`MYPETS_ENVIRONMENT=production` 时，系统默认关闭启动自动建表。即使显式配置为开启，后端也会拒绝启动，并提示先执行：

```bash
alembic upgrade head
```

推荐部署顺序：

1. 备份数据库和对象存储；
2. 将应用实例置于维护或停止写入状态；
3. 执行 `alembic upgrade head`；
4. 执行 `alembic current` 和 `alembic check`；
5. 启动新版本应用；
6. 验证 `/health`、登录、宠物列表、消息、提醒、素材发布、撤销事件和设备回执链路；
7. 恢复流量。

## 五、从 001 增量升级

已经标记为 `001_initial_schema` 的数据库直接执行：

```bash
cd backend
alembic current
alembic upgrade 002_asset_revocation_ack
alembic current
alembic check
```

升级只新增回执表和两个索引，不修改已有 35 张业务表。部署前仍应备份数据库；在高并发生产环境中，应在维护窗口执行并监控 DDL 锁等待。

需要验证单步回退时：

```bash
alembic downgrade 001_initial_schema
```

该操作删除设备清理回执表及其中的回执历史，不会删除版权存证、制作产物、专属 Release 或宠物数据。生产环境执行前必须确认回执数据可丢弃或已经备份。

## 六、接管历史 create_all 数据库

历史数据库不能直接执行初始 Revision，因为数据库中已经存在业务表。必须先确认它与当前 SQLAlchemy Metadata 完全一致。

### 1. 备份

在任何 stamp 操作前制作可恢复备份。SQLite 应复制数据库文件；PostgreSQL 应使用组织现有备份机制或 `pg_dump`。

### 2. 结构比对

```bash
cd backend
python scripts/check_existing_schema.py
```

该工具会比较：

- 表及列；
- 字段类型和可空性；
- 服务端默认值；
- 外键、唯一约束和索引；
- 投稿、制作、D3 部署、视觉身份、版权治理和设备清理回执等全部 36 张业务表。

只有输出以下信息时才能继续：

```text
Existing database schema matches MyPets metadata.
```

发现差异时必须停止接管，根据差异补迁移或修复历史数据库；不得为绕过检查直接 stamp。

### 3. 标记版本

结构确认无误后执行：

```bash
alembic stamp head
alembic current
alembic check
```

`stamp` 只写入 Alembic 版本标记，不创建、删除或修改业务表。已经标记为 `001_initial_schema` 的数据库不得直接 stamp 到 head，应执行 `alembic upgrade head`，确保第二个 Revision 实际创建回执表。

## 七、回退验证

开发和预发布环境应执行完整回退测试：

```bash
alembic upgrade head
alembic downgrade 001_initial_schema
alembic upgrade head
alembic downgrade base
alembic upgrade head
alembic check
```

生产环境不得把 `downgrade base` 作为常规回滚手段。生产回滚应优先采用：

- 发布前数据库备份恢复；
- 针对单个 Revision 编写并验证可逆 downgrade；
- 应用版本与数据库版本协同回退；
- 对不可逆数据变更采用前向修复迁移。

## 八、新增迁移

修改 SQLAlchemy 模型后：

```bash
cd backend
alembic revision --autogenerate -m "describe schema change"
```

生成后必须人工检查：

- 表和列是否完整；
- 外键和删除策略是否正确；
- 索引及唯一约束是否符合业务状态机；
- 数据迁移是否需要先填充再改为非空；
- SQLite `batch_alter_table` 与 PostgreSQL DDL 是否均可执行；
- downgrade 是否安全、完整且顺序正确。

随后执行：

```bash
alembic upgrade head
alembic check
pytest -q
```

## 九、持续集成

`.github/workflows/database-migrations.yml` 对每次后端结构相关变更执行：

- SQLite 从空库升级到 `002_asset_revocation_ack`；
- 检查 36 张业务表和 Alembic 版本表；
- SQLite 单步降级到 `001_initial_schema` 并确认回执表删除；
- SQLite 降级到 base 后重新升级；
- 历史 `create_all` 数据库结构比对、stamp 和漂移检查；
- PostgreSQL 16 执行相同的 head、单步降级、base 降级和重新升级链路；
- 迁移脚本与 SQLAlchemy Metadata 的一致性检查。

数据库迁移 CI、Linux/Windows 测试、Web JavaScript 校验和 Qt 冒烟必须全部通过后才能合并。
