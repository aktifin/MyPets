# MyPets 多人云养桌面宠物优化方案 (已同步最新 1225222 提交)

基于完整产品技术方案与最新代码库（commit `1225222`: *Add realtime cursor notifications with REST fallback*）的逐项对照分析。

---

## 一、现有实现盘点

### 当前已落地能力

下表列出代码库中已实现且可运行的功能模块：

| 能力域 | 已实现 | 对应代码 |
|---|---|---|
| **账户与认证** | 注册/登录/JWT/设备密钥/凭据管理/WS Ticket 认证 | [api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/api.py), [realtime_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/realtime_api.py) |
| **实时通信 (WS)** | **【最新落地】** WebSocket 双向长连接 (`/ws/v1/cursor`) + 短时 WS Ticket + Qt/Web 客户端自动重连与 REST 轮询降级 | [realtime_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/realtime_api.py), [realtime.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/realtime.py), [realtime.js](file:///d:/Project/MyPets/backend/src/mypets_backend/user_portal_static/realtime.js) |
| **多宠物** | Pet 模型含模板/成长/日常属性，AccountPetRelation 含角色/亲密度 | [models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/models.py#L67-L113) |
| **成长系统** | 五阶段 + 等级 + 经验 + 六维日常属性 + 延迟结算 | [domain.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/domain.py#L16-L112), [pet_settlement.py](file:///d:/Project/MyPets/backend/src/mypets_backend/pet_settlement.py) |
| **共同照料** | owner/co_owner/caregiver/viewer 四角色 + 邀请/审批 | [social_models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/social_models.py#L80-L101), [social_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/social_api.py) |
| **好友系统** | 好友申请/接受/拒绝/黑名单/隐私可见度 | [social_models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/social_models.py#L14-L77) |
| **消息系统** | 会话/消息/回执/已读同步/折叠通知域模型 | [messaging_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/messaging_api.py), [message_drawer.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/message_drawer.py) |
| **异步串门** | 邀请/接受/拒绝/召回/送客/时间到期/状态机 | [visit_models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/visit_models.py), [visit_app.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/visit_app.py) |
| **提醒接入** | MyReminder 适配/提醒实例/贪睡/离线缓存/提醒卡片 | [reminder_models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/reminder_models.py), [reminder_manager.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/reminder_manager.py) |
| **边缘半隐藏** | 左右吸附/延迟隐藏/鼠标展开/多显示器/状态持久化 | [edge_dock.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/edge_dock.py), [edge_geometry.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/edge_geometry.py) |
| **宠物模板管理** | 模板 CRUD/版本/审核/发布/资产部署/回滚/RBAC | [admin_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/admin_api.py), [admin_governance_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/admin_governance_api.py) |
| **素材资产** | 素材包上传/SHA256/Manifest/预览/发布/CDN 对象键 | [asset_packages.py](file:///d:/Project/MyPets/backend/src/mypets_backend/asset_packages.py), [pet_assets.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/pet_assets.py) |
| **云端同步** | 语义事件/幂等键/游标游走/增量拉取/离线补偿 | [cloud_session.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/cloud_session.py), [sync_apply.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/sync_apply.py) |
| **本地存储** | SQLite 持久化宠物/消息/提醒/同步游标 | [local_store.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/local_store.py) |
| **投喂/互动** | PC 端宠物照料面板 + 后端 pet care API | [pet_care_panel.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/pet_care_panel.py), [pet_care_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/pet_care_api.py) |
| **Web 管理台** | Admin HTML/JS 静态页面 + Console API | [admin_console_static/](file:///d:/Project/MyPets/backend/src/mypets_backend/admin_console_static) |
| **Web 用户门户** | 用户端注册/登录/宠物/好友/串门/实时通知 Web 客户端 | [user_portal_static/](file:///d:/Project/MyPets/backend/src/mypets_backend/user_portal_static) |
| **桌面窗口** | 透明窗口/连续动画/高 DPI/拖拽/表情增强层/自拍气泡 | [window.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/window.py) |
| **单元测试** | 102 项测试覆盖前后端 + 实时 WS + 串门 + 提醒 + 管理台 | [tests/](file:///d:/Project/MyPets/tests), [backend/tests/](file:///d:/Project/MyPets/backend/tests) |

---

## 二、产品方案缺口矩阵（已更新）

| 产品方案要求 | 现状 | 缺口等级 | 说明 |
|---|---|---|---|
| **一个账户多只宠物** | ✅ 已实现 | — | Pet + AccountPetRelation 模型就绪 |
| **WebSocket 实时通信** | ✅ **已实现** | — | **最新 1225222 提交已落地长连接与游标补偿** |
| **宠物成长五阶段** | ✅ 已实现 | 🟡 小补 | 升级条件判定逻辑需从方案规格补全（陪伴天数/任务/照料质量） |
| **性格路线演化** | 🟡 字段存在 | 🟡 小补 | `personality_type` 字段存在，缺长期行为采集→性格累积逻辑 |
| **共同照料** | ✅ 已实现 | — | 四角色/邀请/审批完整 |
| **好友与社交** | ✅ 已实现 | — | 好友/黑名单/隐私已落地 |
| **宠物消息折叠** | ✅ 已实现 | 🟡 小补 | 消息分组标签（好友宠物/串门留言/成长通知等）尚需扩展 |
| **跨端已读同步** | ✅ 已实现 | — | MessageReceipt + state 机器就绪 |
| **异步串门** | ✅ 已实现 | — | 完整邀请/接受/召回/到期自动完成 |
| **PC 实时串门** | 🟡 串门状态存在 | 🔴 缺失 | 缺 `GuestPetWindow`、访客素材下载、双宠桌面并存 |
| **多宠物聚会** | ❌ 未实现 | 🔴 缺失 | 缺 `pet_gatherings` 模型、`GatheringSceneCoordinator`、多窗口编排 |
| **GuestPetWindow** | ❌ 未实现 | 🔴 缺失 | 方案要求独立窗口、不访问本机私人数据 |
| **多只常驻宠物同屏** | ❌ 未实现 | ⚪ 暂缓 | 方案 MVP 首版明确暂不包含 |
| **MyReminder 接入** | ✅ 已实现 | 🟡 小补 | 休眠恢复合并摘要、串门时备用宠物提醒需完善 |
| **边缘吸附半隐藏** | ✅ 已实现 | 🟢 完成 | 左右/多显示器/吸附状态持久化/动画就绪 |
| **管理员模板平台** | ✅ 已实现 | 🟡 小补 | 缺视觉身份档案（`pet_visual_identities`）、一致性检查、版权表 |
| **宠物形象版本** | ✅ 已实现 | 🟡 小补 | `identity_version/asset_version` 已有，用户外观锁定逻辑需补充 |
| **AI 文字聊天** | ❌ 未实现 | 🔴 缺失 | 缺 `pet_ai_profiles`、`ai_conversations`、AI 人格、记忆管理 |
| **AI 语音聊天** | ❌ 未实现 | 🔴 缺失 | 缺 ASR/TTS 集成、`voice_profiles` |
| **微信小程序** | ❌ 未实现 | 🔴 缺失 | 后端 API 可复用，缺小程序前端 |
| **PostgreSQL 迁移** | ❌ 未迁移 | 🟡 中等 | 后端使用 SQLite，生产需迁移 PostgreSQL |
| **Redis 在线状态** | ❌ 未实现 | 🟡 中等 | 游标当前在内存与 DB 中，分布部署需 Redis |

---

## 三、分阶段优化路线（调整后）

由于 **WebSocket 实时通信通道已在 1225222 提交中全面落地**，实施路线顺延调整如下：

### 阶段 A：架构基线加固与 DB 迁移准备（预计 1 周）
1. **引入 Alembic 数据库迁移**（替代现有的自动 `create_all`）。
2. **PC 客户端分层目录调整**（渐进式拆分 `presentation/` `domain/` `application/` `infrastructure/`）。
3. **成长升级条件与性格路线**（补全完整成长里程碑与性格倾向计算）。

### 阶段 B：GuestPetWindow 与实时串门窗口（预计 2 周）
1. **`GuestPetWindow` 独立窗口**：独立无私人数据权限的访客窗口，包含一键送客与离线/异常返家防护。
2. **外出标识 `AwayIndicator`**：主宠物外出串门时显示桌面折叠外出图标与详情菜单。

### 阶段 C：消息分组与提醒休眠恢复（预计 1 周）
1. **消息分组标签**：按好友宠物、串门留言、共同照料、成长通知进行会话分类。
2. **提醒休眠恢复**：休眠唤醒后合并错过提醒为摘要，避免连续触发多个提醒动画。

### 阶段 D：视觉身份档案与版权校验（预计 1-2 周）
1. **`pet_visual_identities` 与 `pet_asset_rights`**。
2. **发布流程增加特征一致性评分与版权核验**。

### 阶段 E：AI 聊天系统（预计 2 周）
1. **AI 人格、有限记忆与情绪联动**（禁止智能体/工具调用）。

### 阶段 F：多宠物聚会（预计 2 周）
1. **`pet_gatherings` 与 `GatheringSceneCoordinator`**。

---

## 四、最新 1225222 提交影响评估

- **新增测试**：`tests/test_realtime.py` (153 行) 和 `backend/tests/test_realtime.py` (115 行)，测试用例从 99 项增至 **102 项**。
- **架构提升**：完成了云端实时通知（实时收到好友申请、串门变更、消息推送）从轮询向 WebSocket 长连接的跨越，并保持完美的 REST 自动降级与断线重连机制。
