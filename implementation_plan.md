# MyPets 多人云养桌面宠物优化方案 (已更新至 v0.7 版本)

基于完整产品技术方案与最新代码库（commit `9536ea6` / v0.7: *完成多宠优化阶段 A 架构加固与阶段 B GuestPetWindow 串门 UI 落地*）的逐项对照分析。

---

## 一、现有实现盘点

### 当前已落地能力

下表列出代码库中已实现且可运行的功能模块：

| 能力域 | 已实现 | 对应代码 |
|---|---|---|
| **账户与认证** | 注册/登录/JWT/设备密钥/凭据管理/WS Ticket 认证 | [api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/api.py), [realtime_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/realtime_api.py) |
| **实时通信 (WS)** | WebSocket 双向长连接 (`/ws/v1/cursor`) + 短时 WS Ticket + Qt/Web 自动重连与 REST 降级 | [realtime_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/realtime_api.py), [realtime.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/realtime.py) |
| **多宠物与成长** | **【v0.7 落地】** 结构化 domain 分层、五阶段自动评估晋升算法、`PetGrowthLog` 成长里程碑与 `PetPersonalityScore` 五向性格积分 | [domain/](file:///d:/Project/MyPets/src/onepic_desktop_pet/domain/), [pet_settlement.py](file:///d:/Project/MyPets/backend/src/mypets_backend/pet_settlement.py) |
| **数据库迁移** | **【v0.7 落地】** Alembic DB 迁移配置 (`alembic.ini`, `env.py`) 及 Base.metadata 23 张表自动化结构校验 | [backend/alembic.ini](file:///d:/Project/MyPets/backend/alembic.ini), [test_alembic_metadata.py](file:///d:/Project/MyPets/backend/tests/test_alembic_metadata.py) |
| **PC 实时串门与访客窗口** | **【v0.7 落地】** `GuestPetWindow` 独立访客窗口（隐私隔离）+ `AwayIndicator` 桌面折叠外出卡片 + 送客 API 端点联动 | [guest_pet_window.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/presentation/guest_pet_window.py), [away_indicator.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/presentation/away_indicator.py) |
| **共同照料** | owner/co_owner/caregiver/viewer 四角色 + 邀请/审批 | [social_models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/social_models.py#L80-L101), [social_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/social_api.py) |
| **好友系统** | 好友申请/接受/拒绝/黑名单/隐私可见度 | [social_models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/social_models.py#L14-L77) |
| **消息系统** | 会话/消息/回执/已读同步/折叠通知域模型 | [messaging_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/messaging_api.py), [message_drawer.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/message_drawer.py) |
| **异步串门** | 完整状态机：邀请/接受/拒绝/召回/一键送客/到期自动归家 | [visit_models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/visit_models.py), [visit_app.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/visit_app.py) |
| **提醒接入** | MyReminder 适配/提醒实例/贪睡/离线缓存/提醒卡片 | [reminder_models.py](file:///d:/Project/MyPets/backend/src/mypets_backend/reminder_models.py), [reminder_manager.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/reminder_manager.py) |
| **边缘半隐藏** | 左右吸附/延迟隐藏/鼠标展开/多显示器/状态持久化 | [edge_dock.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/edge_dock.py), [edge_geometry.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/edge_geometry.py) |
| **宠物模板管理** | 模板 CRUD/版本/审核/发布/资产部署/回滚/RBAC | [admin_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/admin_api.py), [admin_governance_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/admin_governance_api.py) |
| **素材资产** | 素材包上传/SHA256/Manifest/预览/发布/CDN 对象键 | [asset_packages.py](file:///d:/Project/MyPets/backend/src/mypets_backend/asset_packages.py), [pet_assets.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/pet_assets.py) |
| **云端同步** | 语义事件/幂等键/游标游走/增量拉取/离线补偿 | [cloud_session.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/cloud_session.py), [sync_apply.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/sync_apply.py) |
| **本地存储** | SQLite 持久化宠物/消息/提醒/同步游标 | [local_store.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/local_store.py) |
| **投喂/互动** | PC 端宠物照料面板 + 后端 pet care API | [pet_care_panel.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/pet_care_panel.py), [pet_care_api.py](file:///d:/Project/MyPets/backend/src/mypets_backend/pet_care_api.py) |
| **启动管理器 GUI** | 集成 Web 门户/门禁管理/撤销审批/全套测试与打包构建 | [local_manager_gui.py](file:///d:/Project/MyPets/tools/local_manager_gui.py) |
| **桌面窗口** | 透明窗口/连续动画/高 DPI/拖拽/表情增强层/自拍气泡 | [window.py](file:///d:/Project/MyPets/src/onepic_desktop_pet/window.py) |
| **单元测试** | **160 项测试** 覆盖前后端 + WS + 访客窗口 + 升级算法 + 管理台 | [tests/](file:///d:/Project/MyPets/tests), [backend/tests/](file:///d:/Project/MyPets/backend/tests) |

---

## 二、产品方案缺口矩阵（v0.7 最新版）

| 产品方案要求 | 现状 | 缺口等级 | 说明 |
|---|---|---|---|
| **一个账户多只宠物** | ✅ 已实现 | — | Pet + AccountPetRelation 模型就绪 |
| **WebSocket 实时通信** | ✅ 已实现 | — | 长连接与游标补偿已全量上线 |
| **PC 客户端领域分层** | ✅ **已实现** | — | **v0.7 已落地 `domain/` 结构化子包** |
| **数据库 Alembic 迁移** | ✅ **已实现** | — | **v0.7 已落地 `alembic.ini` 与 23 表校验** |
| **宠物成长五阶段与评估** | ✅ **已实现** | — | **v0.7 已落地陪伴天数+经验自动晋升评估** |
| **性格路线演化** | ✅ **已实现** | — | **v0.7 已落地 `PetPersonalityScore` 五向积分模型** |
| **PC 实时串门与访客窗口** | ✅ **已实现** | — | **v0.7 已落地 `GuestPetWindow`（隐私隔离）** |
| **外出标识 AwayIndicator** | ✅ **已实现** | — | **v0.7 已落地桌面折叠外出卡片与提前召回** |
| **一键送客 / 提前返家** | ✅ **已实现** | — | **v0.7 已落地 `POST /api/v1/visits/{visit_id}/send-home` 端点与菜单** |
| **共同照料** | ✅ 已实现 | — | 四角色/邀请/审批完整 |
| **好友与社交** | ✅ 已实现 | — | 好友/黑名单/隐私已落地 |
| **跨端已读同步** | ✅ 已实现 | — | MessageReceipt + state 机器就绪 |
| **异步串门状态机** | ✅ 已实现 | — | 完整邀请/接受/召回/送客/到期自动完成 |
| **边缘吸附半隐藏** | ✅ 已实现 | — | 左右/多显示器/吸附状态持久化/动画就绪 |
| **宠物消息折叠** | ✅ 已实现 | 🟡 小补 | 消息分组分类标签（好友宠物/串门留言/成长通知）尚需界面化归类 |
| **MyReminder 接入** | ✅ 已实现 | 🟡 小补 | 休眠恢复合并摘要、串门时备用宠物提醒需完善 |
| **管理员模板平台** | ✅ 已实现 | 🟡 小补 | 缺视觉身份档案（`pet_visual_identities`）、一致性检查、版权表 |
| **宠物形象版本** | ✅ 已实现 | 🟡 小补 | `identity_version/asset_version` 已有，用户外观锁定逻辑需补充 |
| **多宠物聚会** | ❌ 未实现 | 🔴 缺失 | 缺 `pet_gatherings` 模型、`GatheringSceneCoordinator`、多窗口编排 |
| **AI 文字聊天** | ❌ 未实现 | 🔴 缺失 | 缺 `pet_ai_profiles`、`ai_conversations`、AI 人格、记忆管理 |
| **AI 语音聊天** | ❌ 未实现 | 🔴 缺失 | 缺 ASR/TTS 集成、`voice_profiles` |
| **微信小程序** | ❌ 未实现 | 🔴 缺失 | 后端 API 可复用，缺小程序前端 |
| **PostgreSQL 迁移** | ❌ 未迁移 | 🟡 中等 | 后端使用 SQLite，生产需迁移 PostgreSQL (Alembic 配置已就绪) |
| **Redis 在线状态** | ❌ 未实现 | 🟡 中等 | 游标当前在内存与 DB 中，分布部署需 Redis |

---

## 三、分阶段优化路线（最新进度）

### ✅ 阶段 A：架构基线加固与 DB 迁移准备（已完成 - v0.7）
1. [x] **引入 Alembic 数据库迁移**（已配置 `alembic.ini` 与 23 张表结构元数据校验）。
2. [x] **PC 客户端分层目录调整**（已创建 `src/onepic_desktop_pet/domain/` 结构化包）。
3. [x] **成长升级条件与性格路线**（已完成 5 阶段判定算法与五向性格积分模型）。

### ✅ 阶段 B：GuestPetWindow 与实时串门窗口（已完成 - v0.7）
1. [x] **`GuestPetWindow` 独立窗口**：无私人数据权限的独立访客桌面窗口，提供打招呼与一键提前送客菜单。
2. [x] **外出标识 `AwayIndicator`**：主宠物外出串门时显示桌面折叠外出胶囊卡片，支持一键提前召回。
3. [x] **一键送客 API 端点**：`POST /api/v1/visits/{visit_id}/send-home` 及前后端控制器联动。

### ⏳ 阶段 C：消息分组与提醒休眠恢复（下一步 - 预计 1 周）
1. **消息分组标签**：按好友宠物、串门留言、共同照料、成长通知进行会话分类。
2. **提醒休眠恢复**：休眠唤醒后合并错过提醒为摘要，避免连续触发多个提醒动画。

### ⏳ 阶段 D：用户上传宠物图 ➔ 资源包制作管线（重点补充方案 - 预计 1-2 周）
1. **用户侧原图提交 API (`POST /api/v1/pet-asset-submissions`)**：
   - 支持用户上传原始宠物图片、指定性格、风格偏好（保留原画风/轻度Q版/完整Q版）。
   - 创建 `UserPetSubmission` 模型记录提交状态 (`pending_processing`, `in_review`, `approved`, `rejected`)。
2. **自动化与管理员制作管线 (Asset Pipeline Builder)**：
   - **系统自动模式**：抠图背景分离 ➔ 动作序列/透明 Spritesheet 图集生成 ➔ `asset_manifest.json` 导出 ➔ `validate_asset_package` 校验 13 种必需动作（`idle`, `walk`, `sit`, `sleep`, `wave`, `happy`, `shy` 等）。
   - **管理员人工审核与精修模式**：管理员在 `/admin` 控制台查看用户原图提交清单，可手动补充动作帧并进行视觉验收。
3. **版本部署与下发**：
   - 审核通过后，打包生成固化素材包 (`identity_version`/`asset_version`)；
   - 更新部署通道指针，客户端和 Web 端通过 `/api/v1/catalog/pet-assets/latest` 自动同步专属形象素材包。

### ⏳ 阶段 E：视觉身份档案与版权校验（预计 1-2 周）
1. **`pet_visual_identities` 与 `pet_asset_rights`**。
2. **发布流程增加特征一致性评分与版权核验**。

### ⏳ 阶段 F：AI 聊天系统（预计 2 周）
1. **AI 人格、有限记忆与情绪联动**（`pet_ai_profiles` 与对话能力）。

### ⏳ 阶段 G：多宠物聚会（预计 2 周）
1. **`pet_gatherings` 与 `GatheringSceneCoordinator`** 组队聚会多窗口编排。

---

## 四、阶段成果评估与验证

- **单元测试**：已成功扩充至 **160 项**（前端/桌面/后端综合）与 **56 项**（后端独立测试），运行通过率 **100%**。
- **隐私与代码安全**：`git add --dry-run .` 保持干净，无未授权私人图片及绝对路径暴露。


