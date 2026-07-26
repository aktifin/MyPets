# MyPets 管理员 Web 管理台

## 一、定位与入口

管理台由 FastAPI 后端直接提供，入口为：

```text
/admin
```

页面只负责展示和发起操作。权限、状态机、幂等、兼容性检查、版权有效期和审计均由服务端执行。管理台不依赖独立 Node.js 构建服务或第二套权限系统。

当前覆盖公共宠物模板、用户原图审核、专属素材制作、版权存证与证据附件、独立复核、D3 部署审核、专属 Release 发布和回退、设备撤销执行与人工跟进、公共发布以及审计日志。

## 二、角色分权

管理台使用账户密码换取短期访问令牌，并通过 `/api/v1/admin/me` 读取角色。令牌仅保存于 `sessionStorage`。

| 角色 | 主要操作 |
|---|---|
| editor | 创建模板和版本、上传素材、管理制作工单、登记版权存证、设置有效期、上传证据、提交 D3 审核 |
| reviewer | 审核模板和用户原图、独立复核版权存证、批准或退回 D3 审核 |
| publisher | 发布公共或专属 Release、撤销版权存证、回退部署、记录设备撤销人工跟进 |
| auditor | 查询审计日志并只读查看治理与设备执行状态 |
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

editor 选择制作产物，填写来源声明与有效期。系统自动把已审核原始投稿关联为证据，管理台同时要求至少选择一个附件。新存证固定进入 `pending`，声明人不能自行复核。

### 2. 证据附件

支持 PDF、PNG、JPEG 和纯文本，单个文件不超过 8 MB。服务端按 SHA-256 去重，元数据保存在数据库，正文保存在对象存储。附件只能由管理员携带短期令牌下载，响应使用 `Cache-Control: private, no-store`。

存证进入 `verified` 或 `revoked` 后，附件和有效期冻结；如需变更授权，应撤销旧存证并创建新的历史版本。

### 3. 独立复核

reviewer 核验权利主体、授权范围、用途、有效期和附件证据。通过后保存复核意见、复核人和 `verified_at`。

声明人不能复核自己的存证，已过期授权不能核验为有效。未来生效的授权可以完成材料复核，但在生效前不能通过 D3 审核或发布。

### 4. 状态历史

系统为登记、原始证据关联、附件上传、有效期调整、独立复核和撤销写入不可变业务历史。业务历史用于查看单条存证完整演进，管理员审计日志用于全局追责。

## 四、D3 发布门禁

D3 批准、专属发布和素材包下载均重新检查最新版权存证：

1. 状态必须为 `verified`；
2. 授权必须已经生效；
3. 授权不得过期；
4. 权利记录必须与制作产物一致。

已发布素材的授权过期或撤销后，服务端下载返回 HTTP 410。撤销还会产生 `asset_revoked` 事件，要求桌面端清理缓存并回退安全形象。

## 五、设备撤销执行与人工跟进

版权撤销后，管理台在“版权与专属部署”页面展示设备执行区域。

聚合统计包括：

- 撤销批次；
- 当前应执行设备；
- 已安全清理设备；
- 清理失败设备；
- 未提交回执设备；
- 仍需人工跟进设备；
- 每批撤销的安全清理完成率。

设备原始状态与人工状态分开保存：

- 设备回执记录客户端实际清理结果，不允许管理员修改；
- publisher 对失败或未回执设备追加 `investigating`、`resolved` 或 `waived` 跟进记录；
- 每次跟进都形成新历史，不覆盖上一条记录；
- `waived` 只表示运营层面不再追踪，不恢复素材分发，也不解除客户端撤销要求。

管理台支持全部、需跟进、未回执、失败、处理中、已解决和已豁免筛选。editor、reviewer 和 auditor 可以只读查看；只有 publisher 和 superadmin 可以新增跟进记录。

## 六、主要接口

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

### 设备撤销执行

```text
GET  /api/v1/admin/governance/revocation-operations
POST /api/v1/admin/governance/revocation-follow-ups
GET  /api/v1/admin/governance/revocation-follow-ups
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

## 七、浏览器安全

管理台资源使用同源 CSP、`Referrer-Policy: no-referrer`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY` 和 `Cache-Control: no-store`。

附件下载通过 JavaScript 携带 `Authorization: Bearer` 请求，再使用临时 Blob URL 触发保存。访问令牌不会进入 URL、查询参数、文件名或审计日志。设备撤销进度使用原生 `<progress>` 元素，不依赖 CSP 禁止的内联样式。

## 八、不可绕过规则

1. 普通账户不能访问 `/api/v1/admin/*`。
2. 版权声明人不能复核自己的存证。
3. editor 才能调整待复核存证的有效期和附件。
4. verified/revoked 存证的附件与条款不可原地修改。
5. 未生效或已过期授权不能批准、发布或继续下载。
6. 制作产物上传者不能审核自己的 D3 产物。
7. 客户端设备回执不能由管理员修改。
8. 只有 publisher/superadmin 可以新增设备撤销跟进记录。
9. 已发布素材包不可覆盖，只能创建新 Release。
10. 所有业务变更写入业务历史或管理员审计日志。

## 九、当前限制

尚未实现：

- 到期前主动预警和到期自动撤销事件；
- 证据附件病毒扫描、电子签章和可信时间戳；
- 视觉身份自动评分和人工对比标注；
- 批量复核、批量撤销与运营导出；
- 设备跟进负责人分派和服务时限统计；
- SSO 和企业身份提供商接入。
