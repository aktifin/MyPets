# MyPets 管理员 Web 管理台

## 一、定位与入口

管理台由 FastAPI 后端直接提供，入口为：

```text
/admin
```

管理台不依赖 Node.js、独立前端构建服务或第二套权限系统。浏览器页面只负责展示和发起操作，所有权限、状态机、幂等、兼容性检查和审计仍由服务端执行。

当前管理台覆盖：

- 公共宠物模板和版本管理；
- 用户宠物原图审核；
- 专属素材制作工单；
- 版权存证登记、独立复核和撤销；
- D3 专属素材部署审核；
- 不可变专属 Release 发布；
- 单宠 active/previous 部署和回退；
- 公共素材发布、稳定通道和回滚；
- 管理员操作审计。

## 二、登录与角色分权

管理台使用账户密码换取短期账户访问令牌，再通过 `/api/v1/admin/me` 读取角色和权限。访问令牌只保存在浏览器 `sessionStorage`，关闭标签页后自动失效；密码不保存，页面不使用长期设备密钥。

生产环境应配置明确的职责分离角色：

```text
MYPETS_ADMIN_EDITORS
MYPETS_ADMIN_REVIEWERS
MYPETS_ADMIN_PUBLISHERS
MYPETS_ADMIN_AUDITORS
MYPETS_ADMIN_SUPERADMINS
```

`MYPETS_ADMIN_USERNAMES` 仅作为兼容性的超级管理员名单。

角色边界：

| 角色 | 主要操作 |
|---|---|
| editor | 创建模板和版本、上传素材、领取原图审核、管理制作工单、登记版权存证、提交 D3 审核 |
| reviewer | 审核模板版本、审核用户原图、独立复核版权存证、批准或退回 D3 部署审核 |
| publisher | 发布公共或专属 Release、切换稳定指针、撤销版权存证、回退专属部署 |
| auditor | 查询管理员审计日志 |
| superadmin | 拥有全部权限 |

页面隐藏按钮只用于减少误操作，不构成授权判断。手工调用接口时，服务端仍会根据当前账户角色重新验证。

## 三、页面结构

```text
总览
├── 模板数量
├── 版本数量
├── 待审核数量
└── 当前稳定发布

宠物模板
├── 模板搜索与创建
├── 版本创建
├── ZIP 上传和进度
├── 连续动画预览
├── 动作能力矩阵
├── 桌面尺寸模拟
├── 版本差异对比
└── 提交、审核和发布

用户原图
├── 等待处理、审核中、已通过和已驳回筛选
├── 鉴权原图预览
├── 领取审核
└── 通过或驳回

素材制作
├── 工单分配
├── 制作状态与进度
├── 补充参考图
├── 失败和重新排队
├── 制作产物上传与校验
└── 受控产物下载

版权与专属部署
├── 制作产物和最新版权状态
├── 版权声明登记
├── reviewer 独立复核
├── publisher 撤销存证
├── 提交 D3 独立审核
├── D3 批准或退回
├── 不可变专属 Release 发布
├── 当前单宠部署
└── active/previous 回退

公共发布
├── 当前稳定通道
├── 不可变公共 Release
└── 稳定版本回滚

审计日志
└── 操作人、动作、资源、详情和时间
```

## 四、版权治理与 D3 操作流程

### 1. 制作产物完成

编辑人员在“素材制作”页面上传声明式 ZIP。服务端执行路径安全、文件数量、解压大小、图片解码、Manifest、模板版本和 13 种动作能力检查。通过后工单进入 `ready`，但不会自动发布。

### 2. 登记版权存证

编辑人员在“版权与专属部署”页面选择制作产物，填写权利类型和来源声明。新存证状态固定为：

```text
pending
```

声明人不能把自己的存证直接标记为已核验。

### 3. 独立复核

reviewer 核验原图来源、授权范围、用途和私有分发边界。声明人和复核人必须不同，复核通过后状态变为：

```text
verified
```

最新权利记录不是 `verified` 时，D3 批准和发布均会被服务端拒绝。

### 4. 提交 D3 审核

只有包含已校验产物的 `ready` 工单可以提交。重复提交同一产物时返回原审核记录，不重复创建状态实体。

### 5. D3 独立审核

reviewer 必须确认：

- 最新版权存证已经核验；
- 宠物视觉身份与原图及参考资料一致；
- 工单、产物、宠物和目标模板版本关联正确；
- Manifest、身份版本和素材版本匹配；
- 素材 Schema 在支持范围内。

制作产物上传者不能审核自己的产物。批准后状态为 `approved`；退回后状态为 `rejected`。

### 6. 发布和部署

publisher 将 `approved` 审核发布为不可变专属 Release，并将其设置为目标宠物的 active Release。首次部署没有 previous Release；后续发布会把原 active Release 保存为 previous。

重复发布已经处于 active 状态的同一 Release 按幂等读取处理，不重复增加宠物 `state_version`，也不重复写入发布事件和审计记录。

### 7. 撤销和回退

版权撤销后：

- 权利记录变为 `revoked`；
- 服务端停止分发关联专属素材包；
- 下载接口返回 HTTP 410；
- 相关账户收到 `asset_revoked` 同步事件；
- 客户端应清理缓存并回退到安全素材。

专属部署回退只交换 active 和 previous 指针，不删除不可变 Release。

## 五、管理台使用的主要接口

### 公共模板和发布

```text
GET  /api/v1/admin/pet-template-versions
GET  /api/v1/admin/pet-template-versions/{version_id}/preview
GET  /api/v1/admin/pet-template-versions/{version_id}/preview-image
GET  /api/v1/admin/pet-asset-releases
```

### 用户原图和制作工单

```text
GET  /api/v1/admin/pet-asset-submissions
POST /api/v1/admin/pet-asset-submissions/{submission_id}/start-review
POST /api/v1/admin/pet-asset-submissions/{submission_id}/approve
POST /api/v1/admin/pet-asset-submissions/{submission_id}/reject

GET  /api/v1/admin/pet-asset-production-jobs
POST /api/v1/admin/pet-asset-production-jobs/{job_id}/assign
POST /api/v1/admin/pet-asset-production-jobs/{job_id}/update
POST /api/v1/admin/pet-asset-production-jobs/{job_id}/artifact
```

### 版权治理

```text
GET  /api/v1/admin/governance/rights
POST /api/v1/admin/governance/rights
POST /api/v1/admin/governance/rights/{right_id}/verify
POST /api/v1/admin/governance/rights/{right_id}/revoke
```

### D3 专属部署

```text
POST /api/v1/admin/pet-asset-production-jobs/{job_id}/submit-deployment-review
GET  /api/v1/admin/pet-asset-deployment-reviews
POST /api/v1/admin/pet-asset-deployment-reviews/{review_id}/approve
POST /api/v1/admin/pet-asset-deployment-reviews/{review_id}/reject
POST /api/v1/admin/pet-asset-deployment-reviews/{review_id}/publish
GET  /api/v1/admin/pet-personal-asset-deployments
POST /api/v1/admin/pet-personal-asset-deployments/{pet_id}/rollback
```

## 六、浏览器安全

管理台 HTML、JavaScript 和 CSS 响应包含：

```text
Content-Security-Policy
Referrer-Policy: no-referrer
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
Cache-Control: no-store
```

内容安全策略限制脚本、样式、图片和网络请求为同源资源，并禁止 iframe 嵌入、插件对象和外部表单提交。

受保护的原图、参考图、预览图和素材包必须通过 `Authorization: Bearer` 获取。访问令牌不得出现在 URL、查询参数、审计日志或下载文件名中。

所有用户输入在写入动态 HTML 前必须经过转义。管理台不加载第三方脚本，不使用 `localStorage` 保存令牌。

## 七、服务端不可绕过规则

1. 普通账户不能访问任何 `/api/v1/admin/*` 业务接口。
2. 模板创建者不能批准自己创建的模板版本。
3. 制作产物上传者不能审核自己的 D3 产物。
4. 版权声明人不能复核自己的存证。
5. 未完成独立版权复核的产物不能批准或发布。
6. D3 批准前必须完成版权和视觉身份两项确认。
7. 发布前再次执行兼容性检查。
8. 已发布素材包不可覆盖，只能创建新 Release。
9. 版权撤销后停止服务端分发。
10. 所有管理操作继续写入管理员审计日志。

## 八、当前限制

当前管理台仍未实现：

- 版权附件证据上传、有效期和历史版本可视化；
- 视觉身份自动评分和人工对比标注；
- 多人实时协同编辑；
- 批量审核、批量发布和批量撤销；
- SSO 和企业身份提供商接入；
- 客户端缓存清理回执和撤销闭环统计。
