# MyPets 桌面云养宠

当前版本：`0.3.0a1`（Alpha）

MyPets 是一个面向 Windows 的桌面云养宠项目。用户可以在桌面上照料宠物，并通过 Web 门户管理多只宠物、好友、共同照料、串门、消息、提醒和多人宠物聚会。

本项目当前适合开发测试、小范围内部试用和种子用户验收，尚未达到面向普通用户公开发布的稳定版本标准。

## 当前产品边界

已实现：

- Windows 透明无边框桌面宠物；
- 站立、跑动、坐下、睡眠、拖拽、自拍和情绪反馈；
- 上下左右四向边缘吸附、半隐藏和多显示器位置恢复；
- 本地体验模式和云端账户模式；
- 一个账户维护多只宠物并按设备切换当前宠物；
- 最多同时展示当前宠物和一只轻量伴随宠物；
- 投喂、玩耍、摸摸、清洁和休息；
- 每日任务、连续陪伴、成长目标、羁绊和成长纪念；
- 好友、屏蔽、隐私和共同照料；
- 好友宠物串门、访客窗口、互动和返家时间线；
- 分类消息、搜索、未读定位、跨端已读和快捷回复；
- 提醒、贪睡、休眠恢复摘要和 MyReminder 数据接入；
- 好友申请、照料邀请、串门、聚会邀请和提醒的统一待办；
- 最多四只宠物的受限多人聚会场景；
- 用户宠物原图投稿、人工审核、素材制作和专属素材部署；
- FastAPI 服务端、Web 用户门户和管理端；
- SQLite 开发环境和 PostgreSQL 迁移验证。

尚未实现：

- 宠物人格 AI 文字聊天；
- 用户可查看和清除的有限记忆；
- 语音识别、语音合成、字幕和打断；
- 小程序或原生移动客户端；
- Agent、工具执行、设备控制和自动代操作。

AI 能力后续只用于自然文字和语音交流，不允许替用户执行电脑操作、照料动作或其他工具任务。

## 快速体验

### 方式一：一键本地体验

需要 Windows 10/11 和 Python 3.12。

首次运行：

```powershell
.\scripts\start_local.ps1
```

脚本会：

1. 检查并建立项目虚拟环境；
2. 安装桌面端和后端依赖；
3. 启动本地 FastAPI 服务；
4. 等待健康检查通过；
5. 打开 Web 用户门户；
6. 启动 Windows 桌面宠物；
7. 桌面宠物退出后关闭本次启动的本地服务。

已经完成环境安装时，可跳过依赖检查：

```powershell
.\scripts\start_local.ps1 -SkipSetup
```

### 方式二：分别启动

建立开发环境：

```powershell
.\scripts\check_environment.ps1
.\scripts\setup_environment.ps1
```

启动后端：

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn mypets_backend.main:app --reload
```

启动桌面宠物：

```powershell
.\scripts\run.ps1
```

启动后可访问：

- 用户门户：`http://127.0.0.1:8000/portal`
- 宠物内容管理台：`http://127.0.0.1:8000/admin`
- API 文档：`http://127.0.0.1:8000/docs`
- 健康检查：`http://127.0.0.1:8000/health`

开发环境默认使用本地 SQLite 和开发专用密钥。生产环境必须配置独立随机密钥、HTTPS、正式数据库迁移和持久化对象存储。

## Windows 客户端构建

建立环境后执行：

```powershell
.\scripts\package_release.ps1
```

脚本会先执行发布元数据检查，再调用 PyInstaller，并生成版本化客户端压缩包：

```text
dist\MyPets-Desktop-0.3.0a1-windows-x64.zip
```

该压缩包是 Windows 客户端，不包含正式云端服务。客户端需要连接已部署的 MyPets 服务端；本地开发体验请使用 `scripts/start_local.ps1`。

仅执行未压缩的 PyInstaller 构建：

```powershell
.\scripts\build.ps1
```

## 测试

桌面端：

```powershell
.\scripts\test.ps1
```

后端：

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest
```

发布前元数据与文档检查：

```powershell
.\.venv\Scripts\python.exe .\tools\release_check.py
```

持续集成覆盖：

- 后端全量测试和 Web JavaScript 语法检查；
- Linux 桌面客户体验回归和 Python 编译；
- Windows 全量测试和 Qt 启动验证；
- SQLite 与 PostgreSQL 升级、漂移、降级和重新升级。

## 安全与数据边界

- Windows 设备密钥保存在 Credential Manager；
- 密码和访问令牌不写入桌面 SQLite；
- Web 账户令牌仅保存在当前浏览器会话；
- 服务端是宠物状态、成长、关系和社交生命周期的权威来源；
- 本地 SQLite 只保存可重建缓存、设备设置和离线事件队列；
- 用户素材发布经过人工制作、独立审核和不可变版本控制；
- 生产环境禁止使用开发默认 JWT 密钥和启动时自动建表。

## 主要文档

- [普通用户安装与使用指南](docs/普通用户安装使用指南.md)
- [发布检查清单](docs/发布检查清单.md)
- [客户体验实施计划](implementation_plan.md)
- [云养宠架构基线](docs/云养宠架构基线.md)
- [PC 本地状态仓库](docs/本地状态仓库.md)
- [后端同步 API](docs/后端同步API.md)
- [桌面云端连接](docs/桌面云端连接.md)
- [宠物形象运行时](docs/宠物形象运行时.md)
- [管理员宠物发布链路](docs/管理员宠物发布链路.md)

## 当前发布判断

`0.3.0a1` 是功能较完整的 Alpha 版本。核心养宠、多宠、社交、消息提醒和聚会已经具备自动化回归，但正式发布前仍需完成：

- Windows 安装程序、卸载和升级体验；
- 远程服务部署与运行监控；
- Web 与 Windows 多账户真实交互验收；
- 账户找回、设备自助管理和数据导出；
- 用户日志导出与故障诊断；
- Web 前端初始化和状态管理整合；
- AI 文字交互与有限记忆的独立安全设计。
