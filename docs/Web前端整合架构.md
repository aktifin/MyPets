# MyPets Web 前端整合架构

## 一、整合目标

MyPets Web 用户门户由基础页面和多个客户体验扩展逐步演进而来。早期扩展可直接覆盖 `refreshAll`、`renderDashboard`、`renderPortalPhase1`、`openConversation` 和 `logout`，并分别监听导航、实时事件与首次加载，容易产生重复请求、渲染顺序不确定和局部失败扩散。

整合采用“统一运行时、保持业务兼容、逐批迁移扩展”的方式，不建立第二套页面、第二份业务状态或新的同步游标。

## 二、统一运行时

`portal-runtime.js` 在 `app.js` 之前加载，提供 `window.MyPetsPortal`。

### 1. 单一启动入口

基础脚本只配置运行时。页面最后的 `portal-bootstrap.js` 调用 `markExtensionsReady()` 后，运行时才恢复登录会话并执行第一次刷新，避免在后续 `defer` 脚本尚未加载完成时捕获半成品入口。

旧的 `phase1-bootstrap.js` 仍作为兼容资源保留，但不再注入页面。

### 2. 刷新合并

统一 `requestRefresh` 负责完整刷新：

- 同时发起的请求复用一个 Promise；
- 刷新期间新增请求只排队一次；
- 当前刷新结束后至多追加一次合并刷新；
- 新模块不得再包装 `refreshAll`。

### 3. 统一导航

运行时通过事件委托处理所有 `button[data-section]`：

- 切换 `.workspace`；
- 更新选中状态和 `aria-current`；
- 收起“更多”菜单；
- 发布 `mypets:section-change`；
- 按功能 `order` 串行执行 `onSectionEnter`。

动态新增的处理记录和聚会按钮无需自行绑定页面切换。

### 4. 功能生命周期

标准功能注册形式：

```javascript
MyPetsPortal.registerFeature({
  id: "feature-id",
  label: "用户可理解的功能名称",
  order: 100,
  mount: async ({ runtime }) => {},
  onRefreshComplete: async ({ reason, activeSection, runtime }) => {},
  onSectionEnter: async ({ sectionId, source, runtime }) => {},
  onPetContextRefresh: async ({ petId, selectedPet, runtime }) => {},
  onCareComplete: async ({ action, petId, runtime }) => {},
  onRealtime: async ({ event, runtime }) => {},
  onLogout: async ({ runtime }) => {},
});
```

运行时同时提供三种投影方式：

- `runFeatureHook`：按顺序等待异步功能；
- `applyFeatureHook`：在当前渲染过程中同步修改上下文；
- `queueFeatureHook`：按钩子名称串行处理异步投影。

每个功能单独捕获异常。局部失败会显示“部分功能暂未完成加载”，不会阻断其他页面。

## 三、已完成的生命周期迁移

### 1. 首页核心 `phase1-core`，顺序 10

负责首页、宠物、成长、消息和提醒基础数据，并发布：

- `onPetContextRefresh`；
- `onCareComplete`；
- `onFilterConversations`；
- `onConversationsRenderComplete`；
- `onConversationOpenRequest`；
- `onConversationOpenComplete`；
- `onRemindersRenderComplete`。

消息和提醒扩展通过投影钩子接入，不再替换核心函数。

### 2. 每日照料 `daily-care`，顺序 100

负责当日照料摘要、冷却、推荐动作和任务卡，不再覆盖宠物刷新、首页渲染、照料动作或退出函数。

### 3. 成长目标 `growth-experience`，顺序 110

在每日照料之后加载，复用最新冷却状态，负责成长目标和纪念册展示。

### 4. 主动关怀 `proactive-care`，顺序 130

通过完整刷新、页面进入、实时事件和退出生命周期管理提示与免打扰状态。

### 5. 待处理事项 `pending-items`，顺序 200

- 完整刷新和实时事件后更新；
- 一分钟轮询只在登录期间存在；
- 操作完成后调用统一刷新；
- 发布 `onPendingItemsRenderComplete`，供详情按钮和聚会邀请投影使用。

### 6. 客户操作 `customer-actions`，顺序 220

统一负责：

- 消息发送；
- 会话关联详情；
- 待办详情按钮；
- 提醒卡片定位；
- 串门时间线；
- 退出清理。

模块使用消息、待办、提醒和串门渲染完成钩子，不再覆盖 `openConversation`、`renderConversations`、`renderPendingItems`、`renderReminders`、串门渲染函数或 `logout`。

### 7. 消息效率 `message-efficiency`，顺序 250

负责消息搜索、窗口化读取、未读定位和账户快捷回复，通过：

- `onFilterConversations` 替换当前筛选结果；
- `onConversationsRenderComplete` 添加搜索摘要；
- `onConversationOpenRequest` 接管增强型会话窗口；
- `onMessageActionsRenderComplete` 投影快捷回复。

不再覆盖消息筛选、列表渲染、会话打开、消息发送或操作区渲染函数。

### 8. 处理记录 `customer-history`，顺序 300

仅进入处理记录页时加载；页面可见且已加载时响应实时事件。

### 9. 设备管理 `device-self-service`，顺序 320

仅进入设置页时读取设备和健康信息；退出时清除设备摘要，撤销和诊断隐私边界不变。

### 10. 宠物串门 `visits`，顺序 350

- 统一导航进入串门页后加载账户、好友和串门状态；
- 页面可见时响应实时事件；
- 发布 `onVisitsRenderComplete`，由客户操作模块添加时间线按钮；
- 不再监听所有主导航按钮；
- 退出时清空串门和好友宠物选择状态。

### 11. 宠物聚会 `party-experience`，顺序 400

- 聚会按钮仅声明 `data-section`；
- 进入聚会页时懒加载；
- 页面可见时响应实时事件；
- 宠物上下文变化后只更新创建条件；
- 发布 `onPartiesRefreshComplete`；
- 不再包装 `refreshAll` 或 `renderDashboard`；
- 不再通过零延时任务补刷。

业务边界保持：最多四只宠物、每个账户一只宠物、一个聚会场景、桌面窗口上限仍为两只。

### 12. 聚会待办 `party-pending`，顺序 410

通过以下钩子接入：

- `onResolvePendingTarget`：将聚会邀请解析为聚会目标；
- `onPendingItemDetailDecorated`：将按钮改为“进入聚会”；
- `onActivateCustomerTarget`：打开聚会页和故事；
- `onPartiesRefreshComplete`：同步刷新待办。

不再包装待办面板、目标解析、目标打开、详情装饰或聚会刷新函数。

## 四、数据加载策略

- 全局刷新：账户、宠物、社交、首页核心、每日照料、成长、主动关怀和待办；
- 页面上下文：消息搜索、快捷回复、未读导航；
- 页面懒加载：处理记录、设备管理、串门和聚会；
- 实时增量：仅刷新当前可见页面、当前会话或当前打开的时间线与故事。

不得为了形式统一，把低频接口重新加入每次全局刷新。

## 五、静态资源与安全

`user_portal_web.py` 使用显式 `_ASSETS` 白名单，通过 `/portal/{asset_path}` 提供资源。未知资源返回 404。

所有资源继续使用：

- `Cache-Control: no-store`；
- 内容安全策略；
- `X-Content-Type-Options: nosniff`；
- `X-Frame-Options: DENY`；
- 禁止摄像头、麦克风、定位和支付权限。

`portal-bootstrap.js` 必须保持为最后一个门户脚本。

## 六、兼容边界

本轮未改变：

- API 地址和请求参数；
- `sessionStorage` 登录令牌方式；
- 宠物、好友、消息、提醒、串门和聚会业务规则；
- 权威实时 WebSocket 和游标；
- 数据库结构与迁移；
- Windows 桌面客户端；
- Agent、工具调用、设备控制和自动照料边界。

最终渲染兼容桥暂时保留，仅重新投影每日照料、成长和主动关怀展示，不请求接口、不读写存储、不建立定时任务。待首页剩余渲染包装清理后删除。

## 七、后续整合顺序

1. 清理首页剩余 `renderDashboard` 和 `renderPortalPhase1` 兼容包装；
2. 删除最终渲染兼容桥；
3. 将动态创建的核心结构逐步迁移为明确模板或组件构建函数；
4. 建立统一加载态、空状态、错误态和操作反馈组件；
5. 完成真实浏览器、多账户和移动宽度人工验收。
