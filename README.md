# 一图桌宠（OnePic Desktop Pet / MyPets）

MyPets 是一个正在向多人云养宠演进的 Windows 桌面宠物项目。当前开发重点是桌面互动、多宠物、好友串门、共同照料、消息提醒和自然聊天体验。

## 当前主要能力

- Windows 透明无边框桌面宠物窗口；
- 站立、跑动、坐下、睡眠、拖拽、自拍和情绪反馈；
- 上下左右四向边缘吸附、半隐藏和多显示器位置恢复；
- SQLite 本地缓存、离线事件队列和同步游标；
- 账户注册、登录、设备绑定和设备撤销；
- 一个账户维护多只宠物并在多端切换当前宠物；
- 服务端权威成长、状态结算和日常照料；
- 好友、屏蔽、隐私和共同照料；
- 好友宠物异步串门、桌面访客窗口和双宠互动；
- 分类消息、跨端已读和 WebSocket 实时游标通知；
- MyReminder 数据同步、桌面提醒、贪睡和休眠恢复摘要；
- 用户宠物原图投稿、审核状态查询和安全图片清理；
- 管理员原图审核、素材制作工单和参考图补充；
- 模板素材审核、不可变发布、稳定通道与回滚；
- 专属素材独立审核、私有 Release、单宠部署和回退；
- 已发布宠物素材目录、SHA-256 校验、客户端下载和本地版本缓存；
- 独立 FastAPI 后端与 PySide6 桌面客户端。

## 宠物审核功能状态
- 透明无边框窗口、桌面置顶和多显示器 DPI 适配；
- 站立、跑动、坐下、入睡、醒来、拖拽和自拍连续动画；
- 摸头、分区点击、连续戳击、悬停注视和情绪反馈；
- 跑动结束后随机站立、坐下或自拍；
- 默认 5 分钟无互动后坐下、10 分钟后入睡；
- 右键尺寸调整、暂停跑动、隐藏和退出；
- 支持左右屏幕边缘吸附、延迟半隐藏、鼠标移入展开和跨屏比例恢复；
- 使用 SQLite 保存本地宠物资料、当前宠物、折叠通知、提醒实例和离线事件队列；
- 首次启动自动建立一个兼容现有单机素材的本地宠物实例；
- 托盘支持账户登录、设备绑定、立即同步和多宠物选择；
- 使用 Qt 原生网络异步执行完整快照与增量同步；
- Windows 设备密钥保存到 Credential Manager，密码和访问令牌不落盘；
- 按 `template_id / identity_version / asset_version` 选择和热切换宠物形象；
- 管理员可创建模板版本、上传 ZIP 素材、双人审核并发布不可变形象包；
- PC 缺少精确云端形象时自动查询目录、校验哈希并安装到版本缓存；
- 同时支持逐帧图片包与固定网格精灵表；
- 内置公开演示宠物与榫榫精灵表宠物；
- 用户可在本地放入自己的自拍成片，不提交到 Git；
- 原图登记后自动作为自拍成片，保持原始像素尺寸；
- 标准角色形象和走路 GIF 必须分别得到用户确认；
- 表情符号由程序独立绘制，换角色后仍可显示闪光、爱心、惊叹号、疑问号、怒气、Zzz 和汗滴；
- 统一的逐帧与精灵表 Manifest 校验工具；
- 独立 FastAPI 后端包，支持账户、设备、宠物、语义增量同步与数据库 Alembic 迁移；
- 4 大卡片板块图形化 GUI 启动管理器（`tools/local_manager_gui.py`），集成 Web 门户 (`/portal`) 与 Web 管理台 (`/admin`)；
- 桌面独立访客窗口 (`GuestPetWindow`) 与桌面外出折叠胶囊卡片 (`AwayIndicator`)，支持桌面实时串门交互与一键提前送客；
- 陪伴天数与成长经验五阶段自动评估晋升算法 (`pet_settlement.py`)；
- PyInstaller Windows 打包脚本。
>>>>>>> 96e9508 (feat: 完成核心养育与聊天打卡、专属 Release 自动发现、视觉身份与版权治理、自适应性格演化、桌面与 Web 端卡哇伊 UI 重构 (200 项测试全通过))

宠物审核、素材制作和发布运营链路已恢复，并作为后端默认功能直接注册，不再依赖 `MYPETS_ENABLE_PET_REVIEW` 开关。

<<<<<<< HEAD
恢复范围：

- 用户宠物原图投稿和审核状态查询；
- 管理员原图领取、通过与驳回；
- 宠物素材制作工单、参考图补充和制作产物管理；
- 专属素材独立审核、私有 Release、鉴权下载和回退；
- 模板素材审核、发布、稳定通道和回滚；
- `/admin` 宠物内容管理台；
- 用户门户“专属形象”入口及相关 JavaScript。

审核链路保留编辑、审核、发布权限分离，制作产物上传者不能审核自己的产物。
=======
仓库已经加入第七批架构基础（v0.7）：

- 多宠物、成长、串门、折叠消息、提醒和云事件的纯领域模型（`src/onepic_desktop_pet/domain/`）；
- SQLite 本地缓存、设备当前宠物、提醒实例、离线 outbox 和同步游标；
- 可运行的账户注册、登录、设备绑定、设备撤销和设备令牌 API；
- 服务端权威宠物资料、账户宠物关系、完整快照和增量事件 API；
- 后端 Alembic 数据库迁移配置 (`backend/alembic/`)，自动校验 Base.metadata 全部 23 张表；
- 桌面端登录与注册窗口、Qt HTTP 传输和云端会话编排；
- 桌面独立访客窗口 (`presentation/guest_pet_window.py`) 与外出胶囊 (`presentation/away_indicator.py`)，实现桌面实时串门与 `/send-home` 提前召回；
- Windows Credential Manager 设备密钥存储；
- 自动完整同步、增量轮询和托盘宠物切换；
- 形象版本目录、精灵表切帧、动作降级、缓存安装和原子热切换；
- 管理员模板、版本、素材审核、审计日志和不可变发布 API；
- 开发环境对象存储、公开素材目录和 PC 自动下载；
- 视觉身份、能力声明、边缘探头和素材版本的 Manifest 规范；
- 不侵入 `PetWindow` 主动画逻辑的边缘吸附控制器；
- 管理员和素材制作者可执行的统一 Manifest 校验命令；
- 明确 AI 仅用于文字与语音聊天，不包含智能体、工具调用和电脑自动操作。

完整边界与实施顺序见：

- [云养宠架构基线](docs/云养宠架构基线.md)
- [PC 本地状态仓库](docs/本地状态仓库.md)
- [后端同步 API](docs/后端同步API.md)
- [PC 桌面云端连接](docs/桌面云端连接.md)
- [宠物形象运行时](docs/宠物形象运行时.md)
- [管理员宠物发布链路](docs/管理员宠物发布链路.md)

当前已完成离线桌宠、纯领域模型重构、Alembic 迁移与桌面独立访客实时串门功能。生产对象存储/CDN、发布签名、小程序和 AI 聊天服务将在后续迭代扩展。
>>>>>>> 96e9508 (feat: 完成核心养育与聊天打卡、专属 Release 自动发现、视觉身份与版权治理、自适应性格演化、桌面与 Web 端卡哇伊 UI 重构 (200 项测试全通过))

## 最快体验

当前本地候选版需要 Python 3.12：

```powershell
.\scripts\check_environment.ps1
.\scripts\setup_environment.ps1
.\scripts\run.ps1
```

环境脚本只在项目内创建 `.venv` 并安装依赖，不自动安装 Python 或 Git，也不修改系统环境变量。

## 启动后端开发服务

```powershell
cd backend
python -m pip install -e ".[dev]"
$env:MYPETS_JWT_SECRET = "替换为至少24字符的随机密钥"
$env:MYPETS_ADMIN_USERNAMES = "pet_editor,pet_reviewer"
$env:MYPETS_ASSET_STORAGE_DIR = ".\mypets-assets"
python -m uvicorn mypets_backend.main:app --reload
```

默认数据库为 `backend/mypets-backend.sqlite3`。生产环境必须使用独立随机密钥、HTTPS、正式数据库迁移、访问限流和持久化对象存储。

启动后访问：

```text
用户门户：http://127.0.0.1:8000/portal
宠物内容管理台：http://127.0.0.1:8000/admin
API 文档：http://127.0.0.1:8000/docs
健康检查：http://127.0.0.1:8000/health
```

## 桌面连接后端

1. 启动后端服务；
2. 启动桌面宠物；
3. 打开托盘菜单中的“云端账户”；
4. 登录或创建账户；
5. 保持默认服务地址 `http://127.0.0.1:8000`；
6. 完成设备绑定并等待首次同步。

设备密钥在 Windows 上保存到 Credential Manager，密码和访问令牌不写入本地数据库。

## 本地一图制作

本地一图制作工具可用于个人桌面素材，也可作为云端投稿和人工制作流程的素材来源。

登记原始图片：

```powershell
.\scripts\start_onepic.ps1 -SourceImage "图片的完整路径"
```

素材和中间文件默认保存在被 Git 忽略的 `user_assets/` 和 `work/` 目录中。

校验宠物 Manifest：

```powershell
.\.venv\Scripts\python.exe .\tools\validate_pet_manifest.py
```

自定义自拍照片可放置为：

```text
user_assets/selfie.png
user_assets/selfie.jpg
user_assets/selfie.jpeg
```

## 测试与打包

桌面端：

```powershell
.\scripts\test.ps1
.\scripts\build.ps1
```

后端：

```powershell
cd backend
python -m pip install -e ".[dev]"
python -m pytest
```

后端测试覆盖投稿、审核、制作工单、独立部署审核、权限分离、私有下载和回退。

## 主要文档

- [实施计划](implementation_plan.md)
- [云养宠架构基线](docs/云养宠架构基线.md)
- [后端同步 API](docs/后端同步API.md)
- [PC 桌面云端连接](docs/桌面云端连接.md)
- [PC 本地状态仓库](docs/本地状态仓库.md)
- [宠物形象运行时](docs/宠物形象运行时.md)
- [专属素材审核与部署](docs/专属素材审核与部署.md)

## 当前后续重点

1. 补齐 D3 管理台审核发布界面、用户门户部署状态和 PC 私有 Release 自动安装；
2. 多宠物状态总览和快捷切换；
3. 日常养宠任务、连续照料奖励和成长反馈；
4. 多宠物聚会和更丰富的双宠互动；
5. 正式 Alembic 迁移链与 PostgreSQL 验证；
6. 无工具调用的宠物人格文字聊天和按键语音交互。
