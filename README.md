# 一图桌宠（OnePic Desktop Pet / MyPets）

上传一张角色图片，生成、配置并优化一个可以在 Windows 桌面上跑动、休息、互动和自拍的桌面宠物。

当前 `v0.1.0` 是从已经可运行的 Python + PySide6 桌宠整理出的开源版本。项目正在按 MyPets 云养宠架构渐进演进，但未完成的云端、小程序和社交能力不会在 README 中标记为已实现。

## 当前功能

- 透明无边框窗口、桌面置顶和多显示器 DPI 适配；
- 站立、跑动、坐下、入睡、醒来、拖拽和自拍连续动画；
- 摸头、分区点击、连续戳击、悬停注视和情绪反馈；
- 跑动结束后随机站立、坐下或自拍；
- 默认 5 分钟无互动后坐下、10 分钟后入睡；
- 右键尺寸调整、暂停跑动、隐藏和退出；
- 支持左右屏幕边缘吸附、延迟半隐藏、鼠标移入展开和跨屏比例恢复；
- 使用 SQLite 保存本地宠物资料、当前宠物、折叠通知、提醒实例和离线事件队列；
- 首次启动自动建立一个兼容现有单机素材的本地宠物实例；
- 用户可在本地放入自己的自拍成片，不提交到 Git；
- 原图登记后自动作为自拍成片，保持原始像素尺寸；
- 标准角色形象和走路 GIF 必须分别得到用户确认；
- 表情符号由程序独立绘制，换角色后仍可显示闪光、爱心、惊叹号、疑问号、怒气、Zzz 和汗滴；
- 宠物 Manifest 2.0 校验工具；
- PyInstaller Windows 打包脚本。

## 云养宠演进基线

仓库已经加入第二批架构基础：

- 多宠物、成长、串门、折叠消息、提醒和云事件的纯领域模型；
- SQLite 本地缓存、设备当前宠物、提醒实例、离线 outbox 和同步游标；
- 视觉身份、能力声明、动作降级、边缘探头和素材版本的 Manifest 规范；
- 不侵入 `PetWindow` 主动画逻辑的边缘吸附控制器；
- 管理员和素材制作者可执行的 Manifest 校验命令；
- 明确 AI 仅用于文字与语音聊天，不包含智能体、工具调用和电脑自动操作。

完整边界与实施顺序见：

- [云养宠架构基线](docs/云养宠架构基线.md)
- [PC 本地状态仓库](docs/本地状态仓库.md)

当前 SQLite 只属于客户端缓存层。云端账户、服务端成长判定、小程序、实时串门、多宠聚会和 AI 聊天服务尚未实现。

## 最快体验

未来正式 Release 会提供可直接运行的 Windows 版本，不需要安装 Python。当前本地候选版请先执行：

```powershell
.\scripts\check_environment.ps1
.\scripts\setup_environment.ps1
.\scripts\run.ps1
```

环境脚本只在项目内创建 `.venv` 并安装依赖，不会自动安装 Python、Git，不会修改系统环境变量，也不会申请管理员权限。缺少 Python 3.12 时会停止并给出提示。

## 从一张图片开始

完成环境安装后，先登记最初上传的图片：

```powershell
.\scripts\start_onepic.ps1 -SourceImage "图片的完整路径"
```

该命令会在 `user_assets/source/` 保留原始文件副本，并生成同分辨率的 `user_assets/selfie.png`。原图、自拍图和流程状态全部被 Git 忽略。

接下来先选择生成风格：`preserve_original`（保留原画风，默认）、`light_chibi`（轻度 Q 版）或 `full_chibi`（完整 Q 版）。生成流程只能先产生一张标准角色形象，登记人物特色并交给用户确认：

```powershell
.\.venv\Scripts\python.exe .\tools\onepic_workflow.py character-candidate `
  --image "标准角色候选图路径" `
  --style preserve_original `
  --feature "有辨识度的脸型和眼型" `
  --feature "原图中的发型、服装和标志性配饰"
```

随后必须打开确认窗口。只有用户亲自查看候选图并点击“符合，这就是我要的角色”后，动作门禁才会通过：

```powershell
.\.venv\Scripts\python.exe .\tools\onepic_workflow.py approve-character
```

生成动作后还必须生成并查看走路 GIF：

```powershell
.\.venv\Scripts\python.exe .\tools\onepic_workflow.py walk-review
.\.venv\Scripts\python.exe .\tools\onepic_workflow.py approve-walk --yes
```

没有完成两个确认，程序不会加载私有角色，个人版本打包也会被阻止。

更换角色后可以生成八种表情符号联系表进行视觉检查：

```powershell
.\.venv\Scripts\python.exe .\tools\render_emotion_preview.py
```

## 宠物 Manifest 校验

修改官方或私有宠物素材后，运行：

```powershell
.\.venv\Scripts\python.exe .\tools\validate_pet_manifest.py
```

也可以指定其他 Manifest：

```powershell
.\.venv\Scripts\python.exe .\tools\validate_pet_manifest.py .\user_assets\pet\manifest.json
```

校验会覆盖基础动作、走路位移曲线、动作降级、边缘形象参数、路径越界和素材缺失。

## 自定义自拍照片

把照片命名为下列任意一种形式：

```text
user_assets/selfie.png
user_assets/selfie.jpg
user_assets/selfie.jpeg
```

通常不需要手动复制：`start_onepic.ps1` 会自动把最初上传的原图转换为全分辨率 `selfie.png`。`user_assets/` 中的图片默认被 Git 忽略。没有提供原图时，自拍动作仍会播放，但不会用生成动画末帧冒充原照片。

## 测试与打包

```powershell
.\scripts\test.ps1
.\scripts\build.ps1
```

默认打包生成不含任何 `user_assets/` 的公开演示版本。只有角色和走路均确认后，才能显式构建个人版本：

```powershell
.\scripts\build.ps1 -IncludeUserAssets
```

打包结果位于：

```text
dist/OnePicDesktopPet/OnePicDesktopPet.exe
```

## 一图制作流程

制作流程应先检查环境，再建立项目、处理原图、生成动作、检查多头多腿和裁切问题、接入行为状态机、运行测试，最后在用户验收后打包。详细流程见：

- [Agent 执行入口](agent-guide/AGENT_GUIDE.md)
- [一图桌宠执行说明书](agent-guide/一图桌宠执行说明书.md)
- [云养宠架构基线](docs/云养宠架构基线.md)
- [PC 本地状态仓库](docs/本地状态仓库.md)
- [素材规范](docs/素材规范.md)
- [角色与走路验收清单](docs/角色与走路验收清单.md)
- [隐私说明](docs/隐私说明.md)
- [GitHub 发布清单](docs/发布清单.md)

## 当前公开状态

当前开发仓库为 `aktifin/MyPets`，默认分支为 `main`。公开发布包仍以仓库 Release 页面和发布清单中的验证结果为准。

## 授权

- 程序代码和项目文档：MIT License；
- `assets/` 中的公开演示美术素材：CC BY-NC 4.0；
- `user_assets/`：不属于公开仓库内容，除非素材所有者另行明确授权。

详细范围和署名方式见 [素材授权说明](ASSETS_LICENSE.md)。
