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

屏蔽仍会撤销好友关系、待处理邀请和双方共享宠物访问。

## 新增 API

```text
GET   /api/v1/portal/dashboard
PATCH /api/v1/portal/account
POST  /api/v1/portal/account/password
PATCH /api/v1/portal/preference
PATCH /api/v1/portal/pets/{pet_id}
```

其余注册、宠物创建、隐私和好友操作继续使用现有 `/api/v1` 接口。

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
- DOM 渲染使用 `textContent` 和节点创建，不把用户输入拼接为 HTML。

## 当前限制

- 该入口是临时用户维护门户，不是完整移动端站点；
- 宠物创建仍需要服务端已支持的模板标识和版本；
- 尚未提供图形化模板商城；
- 尚未提供头像上传、邮箱和手机号；
- 密码修改不会主动撤销已经绑定的设备凭据；
- 好友刷新当前为用户主动刷新，没有 WebSocket 实时推送；
- Web 当前宠物与设备当前宠物保持独立。
