# MyPets Web 前端整合架构

## 一、整合目标

MyPets Web 用户门户由基础页面和多个客户体验扩展逐步演进而来。此前每个扩展脚本可以直接覆盖 `refreshAll`、`renderDashboard`、`renderPortalPhase1` 和 `logout`，并分别监听导航、实时事件和首次加载，容易产生以下问题：

- 首次打开时基础脚本先刷新一次，扩展脚本再补刷一次；
- 多个操作同时触发刷新时，相同接口可能重复请求；
- 导航切换由多个脚本分别处理，新增页面需要重复绑定；
- 某个扩展加载失败时，错误可能中断后续功能；
- 静态资源路由逐文件声明，新增脚本容易遗漏路由或安全响应头。

本轮采用“建立统一运行时、保持业务兼容、逐批迁移扩展”的方式，不一次性重写全部页面。

## 二、统一运行时

`portal-runtime.js` 在 `app.js` 之前加载，提供 `window.MyPetsPortal`，主要职责如下：

### 1. 单一启动入口

基础脚本不再立即执行匿名初始化函数，而是在所有 `defer` 扩展脚本注册和包装完成后调用 `MyPetsPortal.start()`。

启动过程只执行一次：

1. 捕获最终的兼容刷新链；
2. 建立统一导航监听；
3. 安装已注册前端功能；
4. 恢复当前登录会话；
5. 执行一次完整刷新；
6. 发布 `mypets:portal-ready` 事件。

旧的 `phase1-bootstrap.js` 仍保留为兼容资源，但不再注入页面，因此不会重复补刷。

### 2. 刷新合并

运行时在全部扩展加载后捕获最终 `refreshAll`，再以统一的 `requestRefresh` 替代全局入口。

当多个操作同时要求刷新时：

- 第一个请求启动真实刷新；
- 后续请求复用同一个 Promise；
- 刷新期间再次提出的请求只排队一次；
- 当前刷新结束后再执行一次合并刷新，而不是按请求数量重复执行。

现有扩展脚本仍可继续包装 `refreshAll`，后续逐批迁移到 `registerFeature` 生命周期。

### 3. 统一导航

运行时通过事件委托处理所有 `button[data-section]`，包括后续动态加入的导航按钮。

切换页面时统一完成：

- 隐藏其他 `.workspace`；
- 更新主导航激活状态；
- 写入 `aria-current="page"`；
- 收起“更多”菜单；
- 聚焦当前工作区；
- 发布 `mypets:section-change` 事件；
- 调用注册功能的 `onSectionEnter`。

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
  onRealtime: async ({ event, runtime }) => {},
  onLogout: async ({ runtime }) => {},
});
```

每个生命周期独立捕获异常。一个扩展失败时：

- 其他功能继续执行；
- 页面顶部显示“部分功能暂未完成加载”；
- 用户可点击“重新加载”；
- 控制台保留具体错误；
- 页面不向用户展示堆栈和内部编码。

## 三、静态资源清单

`user_portal_web.py` 使用一个显式 `_ASSETS` 清单管理用户门户脚本和样式，统一通过 `/portal/{asset_path}` 提供。

所有资源继续使用：

- `Cache-Control: no-store`；
- 内容安全策略；
- `X-Content-Type-Options: nosniff`；
- `X-Frame-Options: DENY`；
- 禁止摄像头、麦克风、定位和支付权限。

资源必须先加入清单才能被访问，未知资源返回 404，避免建立任意文件读取入口。

## 四、兼容边界

本轮没有改变：

- API 地址和请求参数；
- 账户令牌仍只保存在 `sessionStorage`；
- 宠物、好友、消息、提醒、串门和聚会业务状态；
- WebSocket 实时游标实现；
- 数据库结构和迁移；
- Windows 桌面客户端；
- Agent、工具调用和设备控制边界。

## 五、后续迁移顺序

后续前端整合按以下顺序推进：

1. 将首页、每日照料、主动关怀和成长扩展从函数覆盖迁移到 `registerFeature`；
2. 将消息、提醒、待办、处理记录和设备管理迁移到统一的 `onSectionEnter`；
3. 将串门和聚会刷新迁移到统一实时事件生命周期；
4. 把动态创建的核心页面结构逐步移回明确的 HTML 模板或组件构建函数；
5. 建立统一加载态、空状态、错误态和操作反馈组件；
6. 完成真实浏览器、多账户和移动宽度人工验收。

迁移期间不得同时维护第二套页面、第二份业务状态或新的同步游标。
