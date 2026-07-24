# MyPets 管理员 Web 管理台

## 当前范围

管理台由 FastAPI 后端直接提供，入口为：

```text
/admin
```

不需要 Node.js、独立前端构建服务或第二套权限系统。页面调用现有管理员 API，所有业务状态仍由后端审核与发布状态机决定。

## 登录与令牌

管理台使用普通账户密码换取短期账户访问令牌，然后验证该账户是否位于：

```text
MYPETS_ADMIN_USERNAMES
```

访问令牌只保存在 `sessionStorage`，关闭浏览器标签页后自动消失。密码不保存，页面不使用长期设备密钥。

管理台 HTML、JavaScript 和 CSS 可以公开加载，但以下数据必须使用 Bearer 令牌访问：

- 宠物模板；
- 模板版本；
- 暂存素材预览；
- 动作能力矩阵；
- 审核操作；
- 发布历史；
- 管理员审计日志。

## 页面结构

```text
总览
├── 模板数量
├── 版本数量
├── 待审核数量
└── 最近发布

宠物模板
├── 模板搜索
├── 模板创建
├── 版本创建
├── ZIP 上传进度
├── 素材预览
├── 动作能力矩阵
└── 提交、审核和发布操作

审核中心
├── 待审核版本
├── 预览入口
├── 批准
└── 退回修改

发布历史
└── 不可变 Release 列表

审计日志
└── 操作人、动作、资源、详情和时间
```

## 预览 API

管理台增加只读查询接口：

```text
GET /api/v1/admin/pet-template-versions
GET /api/v1/admin/pet-template-versions/{version_id}/preview
GET /api/v1/admin/pet-template-versions/{version_id}/preview-image
GET /api/v1/admin/pet-asset-releases
```

`preview` 返回：

- Manifest；
- 渲染类型；
- 每个动作的原生帧数；
- 动作是否使用降级；
- 实际降级来源动作；
- 受保护的预览图地址。

预览图接口支持逐帧图片和固定网格精灵表。服务端从已经通过发布校验的 ZIP 包中读取图片，不把暂存 ZIP 暴露为公开下载。

## 浏览器安全

管理台响应包含：

```text
Content-Security-Policy
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Cache-Control: no-store
```

内容安全策略限制脚本、样式、图片和网络请求为同源资源，并禁止 iframe 嵌入、插件对象和外部表单提交。

素材预览必须通过 `Authorization: Bearer` 请求获取。访问令牌不得出现在图片 URL、查询参数、审计日志或下载文件名中。

## 操作边界

管理台不能绕过以下规则：

1. 创建者不能批准自己创建的模板版本。
2. 未上传并校验 ZIP 的版本不能提交审核。
3. 只有审核中的版本可以批准或退回。
4. 只有已批准版本可以发布。
5. 已发布素材包不可覆盖。
6. 所有管理操作继续写入服务端审计日志。
7. 页面显示的按钮状态不构成权限判断，服务端始终重新验证。

## 当前限制

当前管理台是无框架的同源单页界面，适合第一阶段运营和审核。尚未实现：

- 管理员角色细分；
- 多人实时协同编辑；
- PC 和小程序设备尺寸模拟器；
- 动画连续播放时间轴；
- 素材差异对比；
- 灰度发布、暂停和回滚；
- 批量审核与批量发布；
- SSO 和企业身份提供商接入。
