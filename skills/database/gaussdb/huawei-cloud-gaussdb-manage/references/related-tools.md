# MCP 工具参考

## 概述

MCP Server 0.3.7 暴露 17 个场景工具和 5 个 OpenAPI 目录/调用工具。以下参数仅列出 Agent
编排时最需要的部分；实际调用以 MCP 返回的输入 Schema 为准。

## 实例与创建

| 工具 | 关键参数 | 关键约束 |
|---|---|---|
| `list_instances` | `name`, `limit`, `marker` | `name` 为精确名称筛选；使用 marker 分页 |
| `get_instance` | `instance_id` | 返回拓扑、网络、存储、标签和慢 SQL 所需 `node_ids` |
| `list_flavors` | `version`, `ha_mode`, `limit`, `marker` | `ha_mode` 可为 `centralization_standard`、`enterprise`、`combined` |
| `discover_create_options` | `ha_mode`, `deployment_mode`, `product_type`, `version`, `limit` | 实时发现版本、规格、AZ、VPC、子网和安全组 |
| `create_instance` | `configuration`, `confirm` | 异步、可能计费；密码不得回显；`logger` 不能直接创建 |
| `delete_instance` | `instance_id`, `confirm` | 永久删除，必须 `confirm=true`，并进行云端二次保护检查 |
| `resize_instance` | `instance_id`, `flavor_ref`, `is_auto_pay`, `confirm` | `flavor_ref` 必须来自实时规格查询 |
| `expand_instance` | `instance_id` 与一个扩容维度 | `new_volume_size_gb`、`coordinator_az_codes`、`dn_shard_count` 三选一 |
| `restart_instance` | `instance_id`, `confirm` | 中断现有连接；先核对实例和维护窗口 |

创建枚举：

- `product_type`: `basic`, `enterprise`, `ecology`
- `ha_mode`: `centralization_standard`（集中式）或 `enterprise`（分布式创建模式）
- `deployment_mode`: `single`, `triset`, `logger`, `combined`, `hws`

基础版分布式的规格族由服务自动映射为 `combined`；企业版/生态版分布式使用 `hws` 候选。
这些值只表达产品组合，是否可售仍由实时返回和创建接口决定。

## 参数、备份与诊断

| 工具 | 关键参数 | 关键约束 |
|---|---|---|
| `get_instance_parameters` | `instance_id`, `name`, `modifiable_only`, `limit`, `marker` | 修改前必须调用；返回只读、值域、重启和风险元数据 |
| `update_instance_parameters` | `instance_id`, `values`, `confirm` | 1-100 个字符串值；敏感/需重启参数需要二次确认 |
| `list_backups` | `instance_id`, `backup_type`, `begin_time`, `end_time`, `limit`, `marker` | 时间范围使用 API 接受的 ISO 8601 格式 |
| `create_manual_backup` | `instance_id`, `name`, `description`, `confirm` | 名称 4-64 字符且字母开头；异步 |
| `get_backup_policy` | `instance_id` | 修改前读取当前策略 |
| `configure_backup_policy` | `instance_id`, `keep_days`, `start_time`, `period`, `differential_period`, `confirm` | `keep_days` 1-732；时间窗为 UTC；差量周期单位为分钟 |
| `analyze_slow_sql` | `instance_id`, `node_ids`, `start_time`, `end_time`, `threshold`, `limit` | 时间是 Unix 毫秒；SQL 文本按敏感数据处理 |
| `get_job` | `job_id` | 跟踪创建、备份、变更、扩容、重启和参数任务 |

## OpenAPI 目录

| 工具 | 用途 | 风险 |
|---|---|---|
| `list_openapi_operations` | 按 `query`、`category`、`risk` 分页检索公开 SDK 操作 | READ |
| `describe_openapi_operation` | 获取指定 operation 的递归请求结构 | READ |
| `invoke_read_openapi` | 调用目录分类为 READ 的操作 | READ |
| `invoke_write_openapi` | 调用目录分类为 WRITE 的操作 | WRITE |
| `invoke_dangerous_openapi` | 调用删除、恢复、切换、升级和计费敏感操作 | DANGEROUS |

标准调用对象：

```json
{
  "operation": "<snake_case_operation>",
  "request": {
    "<field>": "<value>"
  }
}
```

必须先 describe，再 invoke。风险通道不匹配、专用工具限制或缺少危险确认时，服务会拒绝调用。

## 常见错误

✅ 正确：先用 `discover_create_options` 得到 `spec_code` 和 AZ，再构造创建配置。

❌ 错误：把北京四查询到的规格码用于贵阳一，或假设所有区域支持同样的数据库版本。

✅ 正确：将 `get_backup_policy` 返回的差量周期整数传给 `configure_backup_policy`。

❌ 错误：把 `differential_period` 当作星期字符串，或将云端历史拼写
`differential_priod` 传给写工具。

✅ 正确：删除标签前先 `describe_openapi_operation`；删除标签的 `instance_id` 和 `key` 位于顶层。

❌ 错误：照搬添加标签的 `body.tags` 数组形态调用删除标签。
