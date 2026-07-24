# MyReminder Provider 同步与提醒管理

## 目标

本批次将 MyReminder 的现有 `HH:MM` 提醒规则正式接入 MyPets：

```text
MyReminder 规则
→ 只读集成服务
→ MyPets 后端 Provider
→ 指定时间窗口内展开 occurrence
→ 服务端权威状态
→ PC 本地缓存与提醒管理
```

MyReminder 负责规则；MyPets 负责具体提醒实例、完成/贪睡/忽略状态、跨设备同步和桌面投递。

## 一、MyReminder 侧配置

MyReminder 仓库新增独立只读进程：

```powershell
$env:MYREMINDER_MYPETS_INTEGRATION_SECRET = "replace-with-at-least-24-characters"
$env:MYREMINDER_DEFAULT_TIMEZONE = "Asia/Shanghai"
$env:MYREMINDER_MYPETS_INTEGRATION_PORT = "3457"
cd server
npm run start:mypets-integration
```

接口：

```text
GET /api/v1/rules?username=<username>
X-MyPets-Integration-Secret: <shared secret>
```

现有规则没有 `weekdays` 时按每日重复处理；存在 `weekdays` 时使用 ISO 星期值 1～7。集成响应不包含密码哈希或登录 token。

## 二、MyPets 后端配置

```powershell
$env:MYPETS_MYREMINDER_BASE_URL = "http://127.0.0.1:3457"
$env:MYPETS_MYREMINDER_INTEGRATION_SECRET = "same-shared-secret"
$env:MYPETS_MYREMINDER_TIMEOUT_SECONDS = "5"
$env:MYPETS_MYREMINDER_LOOKBACK_DAYS = "1"
$env:MYPETS_MYREMINDER_HORIZON_DAYS = "14"
```

服务地址与密钥必须同时配置；密钥少于 24 个字符时后端拒绝启动。

MyPets 账户用户名必须与 MyReminder 用户名一致。映射只使用标准化用户名，不共享两套系统的账户密码。

## 三、Provider API

```text
GET  /api/v1/reminder-providers/myreminder/status
POST /api/v1/reminder-providers/myreminder/sync
```

同步接口接受当前 MyPets 账户或设备令牌，服务端按账户用户名请求 MyReminder 规则。

默认窗口：

```text
当前时间 - 1 天
至
当前时间 + 14 天
```

每个规则按其 IANA 时区和星期集合展开。稳定 occurrence 来源标识为：

```text
<rule-id>:<local-date>
```

## 四、同步规则

- 新 occurrence：创建为 `pending`；
- 规则时间或内容变化：更新非终态、未贪睡 occurrence；
- 已完成、已忽略或已过期：保持终态；
- 用户已贪睡：保留本机/服务端已调整的时间，不被来源快照复位；
- 规则停用或删除：窗口内对应非终态 occurrence 变为 `expired`；
- 所有创建、更新和过期变化写入账户增量事件流。

事件类型：

```text
reminder_occurrence_upserted
reminder_expired
```

## 五、PC 提醒管理

托盘新增：

```text
提醒管理…
```

管理界面支持：

- 查看未来与待处理提醒；
- 查看完成、忽略和过期历史；
- 查看全部提醒；
- 手动同步 MyReminder；
- 刷新服务端提醒快照；
- 完成选中提醒；
- 贪睡 5、10 或 30 分钟；
- 忽略选中提醒；
- 重新打开到期提醒卡。

同步按钮只调用 MyPets 后端。MyReminder 集成密钥不会进入 PC 配置、SQLite、日志或 Credential Manager。

## 六、安全与故障边界

- MyReminder 集成接口是独立只读服务；
- Provider 响应必须与请求用户名一致，否则整次同步失败；
- 时区、时间、星期和字段长度均在 MyPets 后端校验；
- Provider 故障返回 `502`，不会伪造同步成功；
- 云端断开时，PC 仍使用已缓存 occurrence 执行本地投递；
- 已完成和已贪睡状态不会被旧来源快照覆盖；
- AI 不参与提醒创建、同步或执行，不包含 Agent 和工具调用。

## 七、当前限制

- MyReminder 原界面当前仍以每日 `HH:MM` 规则为主；接口已兼容可选 `weekdays` 和 `timezone` 字段；
- 没有后台周期拉取任务，当前由 PC 用户主动触发 Provider 同步；
- MyReminder 规则停用不会回写 MyPets 状态之外的数据；
- 尚未实现小程序提醒管理和 WebSocket 推送；
- 公网部署仍需 HTTPS、网络访问控制和独立密钥轮换。
