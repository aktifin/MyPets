# MyPets Web 用户门户

## 入口

启动后端后访问：

```text
/portal
```

根路径 `/` 会跳转至 `/portal`。管理员控制台仍位于：

```text
/admin
```

## 功能

### 账户注册与维护

- 注册 MyPets 账户；
- 使用用户名和密码登录；
- 修改显示名称；
- 验证当前密码后修改密码；
- 退出当前浏览器会话。

用户名仍使用现有规则：

```text
A-Z a-z 0-9 _ . -
```

密码长度为 12～128 个字符。

### 宠物选择

Web 门户保存独立的账户级当前宠物偏好：

```text
account_web_preferences.selected_pet_id
```

该选择用于 Web 页面，不直接覆盖每台 PC 设备的 `active_pet_id`。PC 仍可以按设备选择当前宠物。

### 宠物创建与配置

Web 可调用现有宠物创建接口，并维护以下安全字段：

- 宠物名称；
- 性格类型；
- 可见范围；
- 是否允许 caregiver 远程照料。

性格类型：

```text
balanced
playful
gentle
energetic
sleepy
curious
```

Web 不允许直接修改：

- 成长等级和经验；
- 羁绊等级和经验；
- 饥饿、精力、心情、清洁、健康、无聊；
- 资源版本和身份版本；
- 所有权角色；
- 照料贡献。

宠物名称或性格更新会发布现有 `pet_updated` 事件，原因字段为：

```text
portal_pet_config
```

所有关联账户的 PC 客户端会通过既有同步流程收到更新。

### 好友与共同照料

Web 页面复用现有社交 API：

- 发送好友申请；
- 接受、拒绝和取消申请；
- 查看好友；
- 解除好友；
- 屏蔽好友；
- 查看和解除屏蔽；
- 发送 caregiver/viewer 邀请；
- 接受、拒绝和取消共同照料邀请。

屏蔽仍会撤销好友关系、待处理邀请、双方共享宠物访问和进行中的串门。

### 异步串门

Web 门户新增独立“异步串门”页面，直接复用服务端权威串门状态机。

用户可以：

- 选择本人拥有或共同拥有、且当前在家的来访宠物；
- 选择好友；
- 加载该好友对当前账户可见的接待宠物；
- 选择 30 分钟、1 小时、2 小时或 4 小时；
- 填写最多 200 字的留言；
- 发送串门申请；
- 接受或拒绝收到的申请；
- 取消自己发出的申请；
- 查看正在进行的串门和预计返家时间；
- 主动召回自己管理的来访宠物；
- 查看最近 100 条串门历史。

接待宠物列表来自：

```text
GET /api/v1/friends/{friend_account_id}/pets
```

该接口已经按好友关系、屏蔽关系和宠物可见范围过滤。页面不会接收或渲染私有宠物。

串门操作继续使用：

```text
POST /api/v1/visits
GET  /api/v1/visits
POST /api/v1/visits/{visit_id}/accept
POST /api/v1/visits/{visit_id}/reject
POST /api/v1/visits/{visit_id}/cancel
POST /api/v1/visits/{visit_id}/recall
```

#### 双方宠物状态卡

收到申请、进行中和历史记录都会显示对称的只读状态卡：

- 宠物名称；
- 当前位置；
- 成长阶段；
- 成长等级；
- 当前心情。

状态卡不提供编辑能力，也不返回饥饿、健康、清洁等更细粒度私人状态。完整数值仍只在有宠物关系的账户自己的宠物页面中展示。

#### 状态一致性

- 接受申请后，来访宠物由服务端变为 `visiting`；
- 来访期间普通照料接口拒绝操作；
- 到期、召回、屏蔽或解除好友后恢复 `home`；
- Web 页面只展示服务端响应，不提前修改宠物位置；
- 宠物位置变化继续通过 `pet_updated` 同步到 PC；
- 串门摘要继续通过 `pet_visit_updated` 发送给双方账户。

### 移动端布局

串门页面针对窄屏做了单独布局：

- 主导航在手机宽度下变为两列按钮；
- 串门表单由四列逐步降为两列和单列；
- 双方宠物状态卡在窄屏下垂直排列；
- 收到和发出的申请列表改为单列；
- 操作按钮保持可触达宽度；
- 页面不依赖横向滚动才能完成申请或处理。

## 新增 API

用户门户专用维护 API：

```text
GET   /api/v1/portal/dashboard
PATCH /api/v1/portal/account
POST  /api/v1/portal/account/password
PATCH /api/v1/portal/preference
PATCH /api/v1/portal/pets/{pet_id}
```

串门、注册、宠物创建、隐私和好友操作继续使用现有 `/api/v1` 接口，没有建立第二套 Web 状态机。

## 浏览器安全

- 页面、脚本和样式均为同源静态资源；
- CSP 禁止第三方脚本、对象和 iframe 嵌入；
- 使用 `X-Frame-Options: DENY`；
- 使用 `Referrer-Policy: no-referrer`；
- 禁用摄像头、麦克风、定位和支付权限；
- 页面和静态资源使用 `Cache-Control: no-store`；
- 账户访问令牌只保存到 `sessionStorage`；
- 不使用 `localStorage`；
- 不使用认证 Cookie，因此当前实现没有 Cookie CSRF 面；
- DOM 渲染使用 `textContent` 和节点创建，不把用户输入拼接为 HTML；
- 账户令牌只进入 `Authorization` 请求头，不进入串门 URL、查询参数或页面历史。

## 当前限制

- 宠物创建仍需要服务端已支持的模板标识和版本；
- 尚未提供图形化模板商城；
- 尚未提供头像上传、邮箱和手机号；
- 密码修改不会主动撤销已经绑定的设备凭据；
- 好友和串门刷新当前为用户主动刷新，没有 WebSocket 实时推送；
- Web 当前宠物与设备当前宠物保持独立；
- 串门状态卡是只读摘要，不包含完整私人宠物状态；
- 尚未实现串门礼物、照片、自动互动奖励和完整 PWA 安装体验。
