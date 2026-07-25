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
- 已发布宠物素材目录、SHA-256 校验、客户端下载和本地版本缓存；
- 独立 FastAPI 后端与 PySide6 桌面客户端。

## 宠物审核功能状态

宠物内容审核和生产运营链路目前不属于核心产品路径，已默认屏蔽。

默认配置：

```text
MYPETS_ENABLE_PET_REVIEW=0
```

关闭时不注册以下功能：

- 用户宠物原图投稿和审核状态查询；
- 管理员原图审核；
- 宠物素材制作工单和参考图补充；
- 专属素材部署审核、私有 Release、下载和回退；
- 模板素材审核、发布、稳定通道回滚和宠物内容管理台；
- `/admin` 页面；
- 用户门户“专属形象”入口及相关 JavaScript。

屏蔽采用功能开关，不删除源代码、数据库表、历史记录或对象文件。已发布素材的只读目录继续保留，现有宠物和桌面缓存不受影响。

仅在兼容验证或专项开发时临时恢复：

```powershell
$env:MYPETS_ENABLE_PET_REVIEW = "1"
```

该开关不是当前生产部署的推荐配置。

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
$env:MYPETS_ENABLE_PET_REVIEW = "0"
$env:MYPETS_ASSET_STORAGE_DIR = ".\mypets-assets"
python -m uvicorn mypets_backend.main:app --reload
```

默认数据库为 `backend/mypets-backend.sqlite3`。生产环境必须使用独立随机密钥、HTTPS、正式数据库迁移、访问限流和持久化对象存储。

启动后访问：

```text
用户门户：http://127.0.0.1:8000/portal
API 文档：http://127.0.0.1:8000/docs
健康检查：http://127.0.0.1:8000/health
```

宠物审核关闭时，`/admin` 和相关 API 不存在于运行时路由表。

## 桌面连接后端

1. 启动后端服务；
2. 启动桌面宠物；
3. 打开托盘菜单中的“云端账户”；
4. 登录或创建账户；
5. 保持默认服务地址 `http://127.0.0.1:8000`；
6. 完成设备绑定并等待首次同步。

设备密钥在 Windows 上保存到 Credential Manager，密码和访问令牌不写入本地数据库。

## 本地一图制作

本地一图制作工具仍可用于个人桌面素材，不依赖已屏蔽的云端审核链路。

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

后端测试套件会显式开启保留的审核代码进行兼容回归，同时单独验证默认关闭状态下相关路由和页面均被屏蔽。

## 主要文档

- [实施计划](implementation_plan.md)
- [云养宠架构基线](docs/云养宠架构基线.md)
- [后端同步 API](docs/后端同步API.md)
- [PC 桌面云端连接](docs/桌面云端连接.md)
- [PC 本地状态仓库](docs/本地状态仓库.md)
- [宠物形象运行时](docs/宠物形象运行时.md)
- [专属素材审核与部署（保留代码说明）](docs/专属素材审核与部署.md)

## 当前后续重点

1. 多宠物状态总览和快捷切换；
2. 日常养宠任务、连续照料奖励和成长反馈；
3. 多宠物聚会和更丰富的双宠互动；
4. 正式 Alembic 迁移链与 PostgreSQL 验证；
5. 无工具调用的宠物人格文字聊天和按键语音交互。
