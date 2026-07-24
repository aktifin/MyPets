# MyPets 后端同步 API

## 当前范围

`backend/` 是 MyPets 第一版可运行的 FastAPI 模块化单体后端，当前负责：

- 账户注册和密码登录；
- 账户访问令牌；
- 设备绑定、设备密钥轮换和设备撤销；
- 设备访问令牌；
- 服务端权威宠物资料和账户宠物关系；
- 完整同步快照；
- 增量语义事件；
- 设备当前宠物；
- 心跳和同步游标。

当前尚未包含好友、串门、聚会、消息、MyReminder 云同步、管理员内容平台、AI 文字聊天或语音服务。

## 目录结构

```text
backend/
├── pyproject.toml
├── README.md
├── src/mypets_backend/
│   ├── api.py
│   ├── config.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   ├── schemas.py
│   ├── security.py
│   └── services.py
└── tests/
```

桌面客户端继续使用根目录的 Python 包。后端依赖不会被装入桌面发布包。

## 启动开发服务

```powershell
cd backend
python -m pip install -e ".[dev]"
$env:MYPETS_JWT_SECRET = "替换为至少24字符的随机密钥"
python -m uvicorn mypets_backend.main:app --reload
```

默认使用开发用 SQLite：

```text
backend/mypets-backend.sqlite3
```

生产环境必须配置：

```text
MYPETS_DATABASE_URL=postgresql+psycopg://...
MYPETS_JWT_SECRET=<独立高强度随机密钥>
MYPETS_ENVIRONMENT=production
```

## 身份与凭据流程

### 账户令牌

```text
用户名和密码
→ Argon2 验证
→ 短时账户访问令牌
```

账户令牌用于：

- 查看账户；
- 绑定和撤销设备；
- 创建宠物；
- 查看账户拥有或照料的宠物；
- 代表账户修改指定设备的当前宠物。

### 设备令牌

```text
账户令牌绑定设备
→ 服务端返回一次性设备密钥
→ 客户端保存到操作系统凭据管理器
→ 使用设备ID和密钥换取设备访问令牌
→ 调用同步接口
```

数据库只保存设备密钥的 HMAC-SHA256 摘要，不保存原始设备密钥。

重新绑定同一个 `public_id` 时：

1. 生成新设备密钥；
2. 增加 `credential_version`；
3. 旧设备密钥失效；
4. 旧设备访问令牌立即失效。

撤销设备同样增加凭据版本，并拒绝后续同步。

## 主要接口

| 接口 | 认证 | 用途 |
|---|---|---|
| `POST /api/v1/auth/register` | 无 | 注册并获取账户令牌 |
| `POST /api/v1/auth/token` | 无 | 密码登录 |
| `POST /api/v1/auth/device-token` | 设备密钥 | 换取设备令牌 |
| `GET /api/v1/accounts/me` | 任意有效令牌 | 当前账户 |
| `POST /api/v1/devices/bind` | 账户令牌 | 绑定或重新绑定设备 |
| `GET /api/v1/devices` | 账户令牌 | 查看账户设备 |
| `DELETE /api/v1/devices/{id}` | 账户令牌 | 撤销设备 |
| `PATCH /api/v1/devices/{id}/active-pet` | 账户或对应设备令牌 | 修改本设备当前宠物 |
| `POST /api/v1/pets` | 账户令牌 | 创建宠物实例 |
| `GET /api/v1/pets` | 任意有效令牌 | 获取可访问宠物 |
| `GET /api/v1/sync/bootstrap` | 设备令牌 | 获取完整同步快照 |
| `GET /api/v1/sync/events` | 设备令牌 | 获取增量事件 |
| `POST /api/v1/sync/heartbeat` | 设备令牌 | 更新在线时间和获取游标 |

## 幂等规则

以下变更接口要求 `Idempotency-Key`：

- 创建宠物；
- 修改设备当前宠物。

幂等键在同一账户内唯一，并与追加式同步事件绑定。

相同请求重试时返回已有资源或当前结果。把同一幂等键用于另一种操作会返回 `409`，避免网络重试造成重复宠物或错误状态覆盖。

## 服务端权威状态

服务端表：

```text
accounts
devices
pets
account_pet_relations
sync_events
```

以下状态由服务端决定：

- 宠物稳定身份；
- 所有权和照料关系；
- 成长阶段、等级和日常数值；
- 宠物位置状态；
- 设备当前宠物；
- 跨端事件序号。

PC SQLite 只保存可重建缓存。客户端不得以本地旧状态覆盖服务端新状态。

## 完整同步快照

`GET /api/v1/sync/bootstrap` 返回：

```json
{
  "schema_version": "1.0",
  "server_time": "2026-07-24T03:00:00Z",
  "account": {},
  "device": {},
  "pets": [],
  "relations": [],
  "cursor": 42
}
```

用途：

- 新设备首次同步；
- 本地数据库重建；
- 增量游标失效后的恢复；
- 账户重新登录后的全量校正。

当前第一版采用 upsert，不主动删除快照中缺失的本地宠物。正式加入宠物删除接口时，需要通过 `pet_deleted` 事件或显式墓碑完成删除，不能仅依赖“本次快照没出现”。

## 增量同步事件

`GET /api/v1/sync/events?after_sequence=42&limit=100`

事件结构：

```json
{
  "sequence_number": 43,
  "event_id": "...",
  "event_type": "pet_created",
  "idempotency_key": "...",
  "created_at": "2026-07-24T03:01:00Z",
  "target_account_id": "...",
  "target_device_id": null,
  "payload": {}
}
```

`target_device_id = null` 表示账户内所有设备可接收。指定设备 ID 时，其他设备的增量查询不会返回该事件。

当前事件包括：

```text
device_bound
device_revoked
pet_created
active_pet_changed
```

后续会扩展：

```text
pet_updated
pet_deleted
relation_updated
message_received
reminder_due
visit_started
gathering_updated
```

## PC 缓存应用器

`src/onepic_desktop_pet/sync_apply.py` 负责把已经获取的 JSON 应用到 `LocalStateStore`。

它负责：

- 校验同步协议版本；
- 校验字段类型和枚举；
- 拒绝无时区时间；
- 拒绝跨账户关系；
- 拒绝发送给其他设备的事件；
- 应用宠物和关系快照；
- 更新设备当前宠物；
- 单调推进同步游标；
- 忽略未知未来事件但继续推进游标。

最后一项使旧客户端在服务端新增事件类型后不会永久卡在同一序号。

当前模块不负责 HTTP 请求，也不保存令牌。下一步由 Qt 网络层负责：

```text
QNetworkAccessManager
→ 获取 bootstrap/events
→ sync_apply 校验
→ LocalStateStore 写入
→ Qt Signal 通知界面刷新
```

## 客户端密钥存储

设备密钥和访问令牌不得保存到：

- SQLite 普通表；
- JSON 配置；
- 日志；
- URL；
- Git 仓库。

Windows 客户端应使用 Windows Credential Manager。账户退出或设备撤销后，应删除对应本机凭据。

## 生产化缺口

当前后端是可运行的第一阶段，不等于生产部署完成。上线前仍需：

1. Alembic 数据库迁移；
2. PostgreSQL 部署和备份恢复；
3. HTTPS 和反向代理；
4. 登录、注册和设备换令牌限流；
5. 密码重置与账户恢复；
6. 邮箱或微信身份绑定；
7. 访问令牌刷新和会话管理；
8. CORS 与可信来源配置；
9. 事件保留、压缩和游标过期策略；
10. 结构化安全日志和审计；
11. WebSocket 在线事件；
12. 管理员角色和权限系统。

## 当前测试

后端测试覆盖：

- 注册、登录和重复用户名；
- 密码不以明文保存；
- 设备密钥不以明文保存；
- 设备令牌交换；
- 设备撤销；
- 重新绑定后的旧密钥和旧令牌失效；
- 创建宠物幂等；
- 幂等键跨操作冲突；
- 完整快照；
- 增量事件和设备定向过滤；
- 心跳和同步游标。

桌面端测试覆盖完整快照应用、跨账户防护、未知事件兼容和设备定向校验。
