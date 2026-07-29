# MyPets Web 前端整合架构

## 一、整合目标

MyPets Web 用户门户由基础页面和多个客户体验扩展逐步演进而来。此前每个扩展脚本可以直接覆盖 `refreshAll`、`renderDashboard`、`renderPortalPhase1` 和 `logout`，并分别监听导航、实时事件和首次加载，容易产生以下问题：

- 首次打开时基础脚本先刷新一次，扩展脚本再补刷一次；
- 多个操作同时触发刷新时，相同接口可能重复请求；
- 导航切换由多个脚本分别处理，新增页面需要重复绑定；
- 某个扩展加载失败时，错误可能中断后续功能；
- 静态资源路由逐文件声明，新增脚本容易遗漏路由或安全响应头。

整合采用“建立统一运行时、保持业务兼容、逐批迁移扩展”的方式，不一次性重写全部页面。

## 二、统一运行时

`portal-runtime.js` 在 `app.js` 之前加载，提供 `window.MyPetsPortal`。

### 1. 单一启动入口

基础脚本只负责配置运行时，不再自行决定门户何时完成启动。页面最后加载的 `portal-bootstrap.js` 是扩展就绪门：只有它明确调用 `markExtensionsReady()` 后，运行时才允许恢复登录会话和执行第一次刷新。

即使浏览器在后续扩展脚本下载期间提前处理基础脚本中的零延时任务，`MyPetsPortal.start()` 也会等待扩展就绪 Promise，因此不会在函数包装链尚未完成时捕获半成品刷新入口。

启动过程只执行一次：

1. `portal-runtime.js` 建立运行时和扩展就绪 Promise；
2. `app.js` 配置账户、状态反馈和基础刷新适配器；
3. 现有 `defer` 扩展脚本依次完成注册、页面安装和兼容函数包装；
4. 最后的 `portal-bootstrap.js` 标记扩展就绪并请求启动；
5. 运行时捕获最终的兼容刷新链；
6. 建立统一导航监听并安装注册功能；
7. 恢复当前登录会话并执行一次完整刷新；
8. 发布 `mypets:portal-ready` 事件。

旧的 `phase1-bootstrap.js` 仍保留为兼容资源，但不再注入页面，因此不会重复补刷。

### 2. 刷新合并

运行时在全部扩展加载后捕获最终 `refreshAll`，再以统一的 `requestRefresh` 替代全局入口。

当多个操作同时要求刷新时：

- 第一个请求启动真实刷新；
- 后续请求复用同一个 Promise；
- 刷新期间再次提出的请求只排队一次；
- 当前刷新结束后再执行一次合并刷新，而不是按请求数量重复执行。

尚未迁移的扩展脚本可以继续包装 `refreshAll`，但新代码不得新增同类包装。

### 3. 统一导航

运行时通过事件委托处理所有 `button[data-section]`，包括后续动态加入的导航按钮。

切换页面时统一完成：

- 隐藏其他 `.workspace`；
- 更新主导航激活状态；
- 写入 `aria-current="page"`；
- 收起“更多”菜单；
- 聚焦当前工作区；
- 发布 `mypets:section-change` 事件；
- 按功能 `order` 顺序执行 `onSectionEnter`。

页面进入钩子使用串行 Promise 队列。用户快速切换多个标签时，前一次刷新不会覆盖后一次页面的最终状态。

`activatePortalSection` 和 `activateCustomerSection` 在启动后映射到统一导航，旧脚本不需要立即重写。

### 4. 功能注册与错误隔离

新功能应通过以下方式注册：

```javascript
MyPetsPortal.registerFeature({
  id: "feature-id",
  label: "用户可理解的功能名称",
  order: 100,
  mount: async ({ runtime }) => {},
  onRefreshComplete: async ({ reason, activeSection, runtime }) => {},
  onSectionEnter: async ({ sectionId, runtime }) => {},
  onPetContextRefresh: async ({ petId, selectedPet, runtime }) => {},
  onCareComplete: async ({ action, petId, runtime }) => {},
  onRealtime: async ({ event, runtime }) => {},
  onLogout: async ({ runtime }) => {},
});
```

运行时同时提供 `runFeatureHook(hook, context)`，供核心页面在宠物上下文刷新或照料完成后按顺序调用扩展能力。

每个生命周期独立捕获异常。一个扩展失败时：

- 其他功能继续执行；
- 页面顶部显示“部分功能暂未完成加载”；
- 用户可点击“重新加载”；
- 控制台保留具体错误；
- 页面不向用户展示堆栈和内部编码。

## 三、已完成的生命周期迁移

### 1. 首页、成长、消息和提醒核心

`phase1.js` 已注册为 `phase1-core`，顺序为 `10`：

- 完整刷新通过 `onRefreshComplete` 加载；
- 页面进入通过 `onSectionEnter` 按页面加载宠物、消息或提醒数据；
- 实时事件通过 `onRealtime` 刷新；
- 手动刷新调用统一 `requestRefresh`；
- 宠物数据完成后调用 `onPetContextRefresh`；
- 照料完成后调用 `onCareComplete`；
- 不再自行监听全部主导航按钮或实时游标。

### 2. 每日照料

`daily-care-experience.js` 已注册为 `daily-care`，顺序为 `100`：

- 宠物切换后通过 `onPetContextRefresh` 获取当日照料摘要；
- 完整刷新和页面进入后补充首页推荐及下一步任务；
- 照料完成后更新冷却、今日任务和成功文案；
- 退出时清空状态；
- 不再覆盖 `refreshPhase1PetData`、`renderPortalPhase1`、`recommendedCare`、`renderCareRecommendation`、`renderNextSteps`、`performPhase1Care` 或 `logout`。

### 3. 成长目标与纪念册

`growth-experience.js` 已注册为 `growth-experience`，顺序为 `110`：

- 在每日照料之后加载，能够复用最新冷却状态；
- 宠物切换、页面进入和照料完成后刷新展示；
- 退出时清空状态；
- 不再覆盖宠物刷新、首页渲染或退出函数。

### 4. 主动关怀

`proactive-care-experience.js` 已注册为 `proactive-care`，顺序为 `130`：

- 完整刷新后读取偏好并评估提示；
- 页面进入时只重绘当前提示或设置；
- 实时事件通过统一 `onRealtime` 重新评估；
- 退出时统一清理定时器和状态；
- 不再覆盖 `refreshAll`、`renderDashboard` 或 `logout`，也不再单独监听实时游标。

## 四、静态资源清单

`user_portal_web.py` 使用一个显式 `_ASSETS` 清单管理用户门户脚本和样式，统一通过 `/portal/{asset_path}` 提供。

所有资源继续使用：

- `Cache-Control: no-store`；
- 内容安全策略；
- `X-Content-Type-Options: nosniff`；
- `X-Frame-Options: DENY`；
- 禁止摄像头、麦克风、定位和支付权限。

资源必须先加入清单才能被访问，未知资源返回 404，避免建立任意文件读取入口。`portal-bootstrap.js` 必须保持为页面最后一个门户脚本，新增扩展不得插入到它之后。

## 五、兼容边界

本轮没有改变：

- API 地址和请求参数；
- 账户令牌仍只保存在 `sessionStorage`；
- 宠物、好友、消息、提醒、串门和聚会业务状态；
- WebSocket 实时游标实现；
- 数据库结构和迁移；
- Windows 桌面客户端；
- Agent、工具调用和设备控制边界。

## 六、后续迁移顺序

后续前端整合按以下顺序推进：

1. 将待办、处理记录、消息效率和设备管理迁移到 `registerFeature`；
2. 将串门和聚会刷新迁移到统一页面进入及实时事件生命周期；
3. 清理剩余 `refreshAll`、`renderNextSteps`、`logout` 和直接实时监听包装；
4. 把动态创建的核心页面结构逐步移回明确的 HTML 模板或组件构建函数；
5. 建立统一加载态、空状态、错误态和操作反馈组件；
6. 完成真实浏览器、多账户和移动宽度人工验收。

迁移期间不得同时维护第二套页面、第二份业务状态或新的同步游标。
