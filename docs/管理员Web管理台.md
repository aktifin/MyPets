# MyPets 管理员 Web 管理台

## 一、定位与入口

管理台由 FastAPI 后端直接提供，入口为：

```text
/admin
```

页面只负责展示和发起操作。权限、状态机、幂等、兼容性检查、版权有效期和审计均由服务端执行。管理台不依赖独立 Node.js 构建服务或第二套权限系统。

当前覆盖：公共宠物模板、用户原图审核、专属素材制作、版权存证与证据附件、独立复核、D3 部署审核、专属 Release 发布和回退、公共发布以及审计日志。

## 二、角色分权

管理台使用账户密码换取短期访问令牌，并通过 `/api/v1/admin/me` 读取角色。令牌仅保存于 `sessionStorage`。

| 角色 | 主要操作 |
|---|---|
| editor | 创建模板和版本、上传素材、管理制作工单、登记版权存证、设置有效期、上传证据、提交 D3 审核 |
| reviewer | 审核模板和用户原图、独立复核版权存证、批准或退回 D3 审核 |
| publisher | 发布公共或专属 Release、撤销版权存证、回退部署 |
| auditor | 查询审计日志 |
| superadmin | 全部权限 |

页面隐藏按钮只用于减少误操作，服务端仍会逐次校验角色。

## 三、版权存证档案

每条版权存证包含：

- 制作产物、权利类型和来源声明；
- 授权开始时间与结束时间；
- 当前状态：`pending`、`verified` 或 `revoked`；
- 当前有效性：`scheduled`、`active` 或 `expired`；
- 声明人、复核人、复核意见及复核时间；
- 撤销原因和撤销时间；
- 证据附件清单；
- 不可变状态历史。

### 1. 登记

editor 选择制作产物，填写来源声明与有效期。系统会自动把已审核的原始投稿图片关联为第一项证据；管理台同时要求至少再选择一个附件，避免只依赖文字声明。

新存证固定进入 `pending`。声明人不能自行复核。

### 2. 证据附件

支持：

```text
application/pdf
image/png
image/jpeg
text/plain
```

单个文件不超过 8 MB。服务端按 SHA-256 去重，元数据保存在数据库，正文保存在对象存储。附件只能由管理员携带短期令牌下载，响应使用 `Cache-Control: private, no-store`。

存证进入 `verified` 或 `revoked` 后，附件和有效期冻结；如需变更授权，应撤销旧存证并创建新的历史版本。

### 3. 独立复核

reviewer 核验权利主体、授权范围、用途、有效期和附件证据。通过后保存复核意见、复核人和 `verified_at`。

以下情况不能通过：

- 声明人尝试复核自己的存证；
- 没有任何证据附件；
- 授权已经过期。

未来才生效的授权可以完成材料复核，但在生效前不能通过 D3 审核或发布。

### 4. 状态历史

系统为以下操作写入不可变业务历史：

- `declared`：登记存证；
- `source_evidence_linked`：关联原始投稿证据；
- `evidence_added`：上传附件；
- `terms_updated`：调整有效期；
- `verified`：独立复核；
- `revoked`：撤销存证。

历史包含操作人、状态快照、意见、时间和结构化详情。管理员审计日志仍同步保留，二者用途不同：业务历史用于查看单条存证完整演进，审计日志用于全局管理员追责。

## 四、D3 发布门禁

D3 批准、专属发布和素材包下载均重新检查最新版权存证：

1. 状态必须为 `verified`；
2. 授权必须已经生效；
3. 授权不得过期；
4. 权利记录必须与制作产物一致。

`scheduled` 或 `expired` 授权不会被视为可发布。已发布素材的授权过期或撤销后，服务端下载返回 HTTP 410；撤销还会产生 `asset_revoked` 事件，要求桌面端清理缓存并回退安全形象。

## 五、主要接口

### 版权存证

```text
GET  /api/v1/admin/governance/rights
POST /api/v1/admin/governance/rights
POST /api/v1/admin/governance/rights/{right_id}/terms
POST /api/v1/admin/governance/rights/{right_id}/verify
POST /api/v1/admin/governance/rights/{right_id}/revoke
```

### 证据与历史

```text
POST /api/v1/admin/governance/rights/{right_id}/evidence
GET  /api/v1/admin/governance/rights/{right_id}/evidence
GET  /api/v1/admin/governance/rights/{right_id}/evidence/{evidence_id}/file
GET  /api/v1/admin/governance/rights/{right_id}/history
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

管理台资源使用同源 CSP、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` 和 `Cache-Control: no-store`。

附件下载通过 JavaScript 携带 `Authorization: Bearer` 请求，再使用临时 Blob URL 触发保存。访问令牌不会进入 URL、查询参数、文件名或审计日志。

## 七、不可绕过规则

1. 普通账户不能访问 `/api/v1/admin/*`。
2. 版权声明人不能复核自己的存证。
3. editor 才能调整待复核存证的有效期和附件。
4. verified/revoked 存证的附件与条款不可原地修改。
5. 已过期授权不能核验为有效。
6. 未生效或已过期授权不能批准、发布或继续下载。
7. 制作产物上传者不能审核自己的 D3 产物。
8. 已发布素材包不可覆盖，只能创建新 Release。
9. 所有业务变更同时写入存证历史和管理员审计。

## 八、当前限制

尚未实现：

- 到期前主动预警和到期自动撤销事件；
- 证据附件病毒扫描、电子签章和可信时间戳；
- 视觉身份自动评分和人工对比标注；
- 批量复核、批量撤销与运营统计；
- SSO 和企业身份提供商接入；
- 管理台设备清理回执聚合与失败设备跟进。
