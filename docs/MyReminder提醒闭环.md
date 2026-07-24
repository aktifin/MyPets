# MyReminder 提醒闭环

本批实现提醒来源适配、服务端权威状态、本地可靠投递、离线命令队列和低打扰提醒卡。

## 边界

- Provider 只生成标准化的提醒实例，不直接操作桌面窗口。
- 服务端保存提醒实例和最终业务状态。
- PC 使用已同步缓存进行本地到点扫描，因此临时离线时仍能显示提醒。
- 完成、贪睡、忽略和投递确认使用幂等命令队列，联网后按顺序重试。
- 提醒功能不使用 AI Agent、工具调用、Shell、浏览器或设备自动操作。

## Provider 协议

`backend/src/mypets_backend/reminder_provider.py` 定义：

- `ReminderProvider`
- `ProviderOccurrence`

具体 MyReminder、日历或其他来源必须先转换为该协议，再调用提醒实例导入 API。

## 服务端状态

提醒实例状态：

- `pending`
- `delivered`
- `seen`
- `snoozed`
- `completed`
- `dismissed`
- `expired`

当前状态流转：

```text
provider import -> pending
pending -> delivered
pending/delivered -> completed
pending/delivered -> dismissed
pending/delivered -> snooze -> pending(new scheduled_at)
```

`completed`、`dismissed` 和 `expired` 是终态。Provider 的新版本不会自动复活终态提醒。

## HTTP API

- `POST /api/v1/reminders/occurrences`
- `GET /api/v1/reminders/occurrences`
- `GET /api/v1/reminders/snapshot`
- `POST /api/v1/reminders/occurrences/{id}/delivered`
- `POST /api/v1/reminders/occurrences/{id}/complete`
- `POST /api/v1/reminders/occurrences/{id}/snooze`
- `POST /api/v1/reminders/occurrences/{id}/dismiss`

来源导入需要账户令牌。投递确认需要设备令牌。状态操作和数据查询均限制在当前账户。

## 同步事件

- `reminder_occurrence_upserted`
- `reminder_delivered`
- `reminder_completed`
- `reminder_snoozed`
- `reminder_dismissed`

PC 仍以现有云同步状态变化作为快照刷新触发器。提醒快照采用对象响应，避免影响原有宠物和消息响应校验。

## PC 本地可靠投递

`ReminderScheduler` 每 15 秒扫描一次当前账户的 `pending` 提醒。

到期时：

1. 本机状态更新为 `delivered`，防止下一次扫描重复展示。
2. 写入 `folded_notifications` 的 `reminder` 类别。
3. 多条逾期提醒一次性发送给提醒卡，作为设备休眠恢复后的合并结果。
4. 投递确认写入提醒命令队列，并在设备会话可用时同步。

## 离线命令队列

`reminder_command_outbox` 保存：

- 账户和提醒实例标识
- 操作类型
- 贪睡分钟数
- 幂等键
- 创建时间

存在待发送命令时，旧云快照不能覆盖本机较新的提醒状态。只有对应命令成功响应才以服务端结果覆盖并删除队列项。

## 提醒卡

提醒卡：

- 不自动抢占输入焦点
- 不播放声音
- 显示在宠物窗口附近
- 多条逾期提醒合并为一个队列
- 支持完成
- 支持 5、10、30 分钟贪睡
- 用户关闭卡片后可从托盘的 `⏰ 提醒` 再次打开已投递提醒

## 当前限制

- 尚未连接真实 MyReminder 数据源；本批只提供 Provider 协议和标准导入 API。
- 尚未实现重复规则编辑器和提醒管理页面。
- 尚未实现小程序提醒 UI。
- 服务端定时任务不负责桌面弹出；桌面投递由本地缓存和调度器完成。
