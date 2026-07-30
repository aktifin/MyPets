# MyPets Web 前端整合架构

## 一、整合目标

MyPets Web 用户门户由基础页面和多个客户体验扩展逐步演进而来。早期扩展可直接覆盖 `refreshAll`、`renderDashboard`、`renderPortalPhase1`、`openConversation`、`performPhase1Care` 和 `logout`，并分别监听导航、实时事件与首次加载，容易产生重复请求、渲染顺序不确定和局部失败扩散。

当前前端统一遵循以下原则：

- 一个运行时；
- 一个登录会话；
- 一个权威刷新入口；
- 一个导航入口；
- 一个实时事件入口；
- 核心函数只由定义它们的脚本维护；
- 扩展功能通过生命周期和投影钩子接入；
- 不建立第二套页面、第二份业务状态或新的同步游标。

## 二、统一运行时

`portal-runtime.js` 在 `app.js` 之前加载，提供 `window.MyPetsPortal`。

### 1. 单一启动入口

基础脚本只配置运行时。页面最后的 `portal-bootstrap.js` 仅执行两项工作：

1. 调用 `markExtensionsReady()`；
2. 调用幂等的 `start()`。

运行时收到扩展就绪信号后，才恢复登录会话并执行第一次刷新。旧的 `phase1-bootstrap.js` 仍作为兼容资源保留，但不再注入页面。

`portal-bootstrap.js` 不再包装渲染函数，也不再维护最终渲染兼容桥。

### 2. 刷新合并

统一 `requestRefresh` 负责完整刷新：

- 同时发起的请求复用一个 Promise；
- 刷新期间新增请求只排队一次；
- 当前刷新结束后至多追加一次合并刷新；
- 新模块不得包装或重新赋值 `refreshAll`。

### 3. 统一导航

运行时通过事件委托处理所有 `button[data-section]`：

- 切换 `.workspace`；
- 更新选中状态和 `aria-current`；
- 收起“更多”菜单；
- 发布 `mypets:section-change`；
- 按功能 `order` 串行执行 `onSectionEnter`。

动态新增的处理记录和聚会按钮只声明 `data-section`，不自行处理页面切换。

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

运行时提供三种投影方式：

- `runFeatureHook`：按顺序等待异步功能；
- `applyFeatureHook`：在当前渲染过程中同步修改上下文；
- `queueFeatureHook`：按钩子名称串行处理异步投影。

每个功能单独捕获异常。局部失败会显示“部分功能暂未完成加载”，不会阻断其他页面。

## 三、核心渲染投影

核心渲染函数直接发布生命周期，不再依赖最终脚本包装。

### 1. 基础账户与社交

`app.js` 在以下位置直接发布：

- `onDashboardRenderComplete`：账户、宠物列表和当前宠物配置完成；
- `onSocialRenderComplete`：好友、申请、屏蔽和共同照料邀请完成。

### 2. 首页核心

`phase1.js` 在首页、成长、消息和提醒完成后直接发布：

- `onPhase1RenderComplete`；
- `onFilterConversations`；
- `onConversationsRenderComplete`；
- `onConversationOpenRequest`；
- `onConversationOpenComplete`；
- `onRemindersRenderComplete`；
- `onPetContextRefresh`；
- `onCareComplete`。

仪表盘重新渲染时，`phase1-core` 可重新投影已有首页状态，但不会递归发布第二次扩展渲染事件。

## 四、已完成的生命周期迁移

### 1. 首页核心 `phase1-core`，顺序 10

负责首页、宠物、成长、消息和提醒基础数据。已删除对 `renderDashboard` 的兼容包装。

### 2. 用户引导 `customer-experience`，顺序 80

负责：

- 导航菜单重排；
- 宠物切换器；
- 简化宠物创建；
- 新手领养；
- 照料推荐；
- 下一步提示。

通过仪表盘、首页、社交、页面进入和退出生命周期更新，不再包装 `refreshAll`、`renderDashboard`、`renderPortalPhase1` 或 `logout`，也不再为导航菜单增加第二套点击处理。

### 3. 每日照料 `daily-care`，顺序 100

负责当日照料摘要、冷却、推荐动作和任务卡，不覆盖宠物刷新、首页渲染、照料动作或退出函数。一秒计时器仅更新本地按钮状态，不请求网络。

### 4. 成长目标 `growth-experience`，顺序 110

在每日照料之后加载，复用最新冷却状态，负责成长目标和纪念册展示。

### 5. 主动关怀 `proactive-care`，顺序 130

通过完整刷新、页面进入、实时事件和退出生命周期管理提示、频率和免打扰状态。

### 6. 多宠总览 `multi-pet-overview`，顺序 180

- 完整刷新后加载多宠状态；
- 仪表盘和首页渲染后重新投影当前宠物；
- 照料完成后刷新并显示下一只宠物提示；
- 首页可见时响应实时事件；
- 一分钟轮询只在登录期间存在；
- 退出时停止轮询并清空状态；
- 不再包装 `refreshAll` 或 `performPhase1Care`。

### 7. 待处理事项 `pending-items`，顺序 200

- 完整刷新和实时事件后更新；
- 一分钟轮询只在登录期间存在；
- 操作完成后调用统一刷新；
- 发布 `onPendingItemsRenderComplete`。

### 8. 客户操作 `customer-actions`，顺序 220

统一负责消息发送、会话关联详情、待办详情按钮、提醒定位、串门时间线和退出清理。

### 9. 消息效率 `message-efficiency`，顺序 250

负责消息搜索、窗口化读取、未读定位和账户快捷回复，不覆盖消息筛选、列表渲染、会话打开或消息发送函数。

### 10. 处理记录 `customer-history`，顺序 300

仅进入处理记录页时加载；页面可见且已加载时响应实时事件。

### 11. 设备管理 `device-self-service`，顺序 320

仅进入设置页时读取设备和健康信息；退出时清除设备摘要，撤销和诊断隐私边界不变。

### 12. 宠物串门 `visits`，顺序 350

统一导航进入串门页后加载账户、好友和串门状态；页面可见时响应实时事件；发布 `onVisitsRenderComplete`。

### 13. 宠物聚会 `party-experience`，顺序 400

进入聚会页时懒加载，页面可见时响应实时事件，不包装 `refreshAll` 或 `renderDashboard`，也不通过零延时任务补刷。

业务边界保持：最多四只宠物、每个账户一只宠物、一个聚会场景、桌面窗口上限仍为两只。

### 14. 聚会待办 `party-pending`，顺序 410

通过目标解析、待办装饰、目标打开和聚会刷新生命周期接入，不包装待办或聚会函数。

## 五、数据加载策略

- 全局刷新：账户、宠物、社交、首页核心、每日照料、成长、主动关怀、待办和多宠总览；
- 页面上下文：消息搜索、快捷回复、未读导航；
- 页面懒加载：处理记录、设备管理、串门和聚会；
- 实时增量：仅刷新当前可见页面、当前会话、当前时间线或首页可见的多宠总览。

不得为了形式统一，把低频接口重新加入每次全局刷新。

## 六、全局入口约束

除权威定义层外，门户扩展不得重新赋值：

```text
refreshAll
renderDashboard
renderPortalPhase1
performPhase1Care
logout
```

扩展不得直接监听 `mypets:realtime-cursor`，统一由运行时分发 `onRealtime`。

仓库测试会扫描全部门户扩展脚本，阻止上述模式重新进入主分支。

## 七、静态资源与安全

`user_portal_web.py` 使用显式 `_ASSETS` 白名单，通过 `/portal/{asset_path}` 提供资源。未知资源返回 404。

所有资源继续使用：

- `Cache-Control: no-store`；
- 内容安全策略；
- `X-Content-Type-Options: nosniff`；
- `X-Frame-Options: DENY`；
- 禁止摄像头、麦克风、定位和支付权限。

`portal-bootstrap.js` 必须保持为最后一个门户脚本。

## 八、兼容边界

本轮未改变：

- API 地址和请求参数；
- `sessionStorage` 登录令牌方式；
- 宠物、好友、消息、提醒、串门和聚会业务规则；
- 权威实时 WebSocket 和游标；
- 数据库结构与迁移；
- Windows 桌面客户端；
- Agent、工具调用、设备控制和自动照料边界。

## 九、后续整合顺序

1. 将动态创建的核心结构逐步迁移为明确模板或组件构建函数；
2. 建立统一加载态、空状态、错误态和操作反馈组件；
3. 清理未注入的旧兼容资源和过时测试夹具；
4. 完成真实浏览器、多账户和移动宽度人工验收。
