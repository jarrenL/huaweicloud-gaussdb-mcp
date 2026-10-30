# MCP 工具参考

## 概述

兼容的 MCP Server 当前至少暴露 20 个场景工具和 5 个 OpenAPI 目录/调用工具。以下参数仅列出
Agent 编排时最需要的部分；实际版本、工具数量和调用参数以 MCP 运行时返回为准。

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
| `analyze_slow_sql` | `instance_id`, `node_ids`, `start_time`, `end_time`, `threshold`, `limit` | 时间是 Unix 毫秒或带时区 ISO 8601；SQL 文本按敏感数据处理 |
| `get_job` | `job_id` | 跟踪创建、备份、变更、扩容、重启和参数任务 |
| `wait_job` | `job_id`, `timeout_seconds`, `poll_interval_seconds` | 最多等待 1800 秒；本地超时后继续等待同一任务，不重复提交写操作 |

## CES 监控

指标的中文含义、单位与读数注意点见 [监控指标参考](monitoring-metrics.md)。

| 工具 | 关键参数 | 关键约束 |
|---|---|---|
| `list_monitoring_metrics` | `instance_id`, `metric_name`, `node_id`, `component_id`, `limit`, `marker` | 实时发现；组件筛选需要节点；保留完整维度和 marker |
| `query_monitoring_metrics` | `instance_id`, `metrics`, `start_time`, `end_time`, `period`, `aggregation`, `max_points` | 每批 1-20 条真实序列；默认最近 20 点；无数据不视作零 |

发现按精确层级查询：instance_id 对应实例层；加真实 node_id 对应节点层；再加 component_id
对应组件层。先用 get_instance 取拓扑；不要用星号或假定实例层包含下层。
`metrics` 可直接复用发现结果条目。namespace 为 `SYS.GAUSSDBV5`；实例、节点和组件维度依次为
`gaussdbv5_instance_id`、`gaussdbv5_node_id`、`gaussdbv5_component_id`，使用每条指标实际返回的
层级。period 可为 `1`、`60`、`300`、`1200`、`3600`、`14400`、`86400`；`1` 表示原始值，
aggregation 强制为 average。`max_points` 为 1-100，摘要不受显示截断影响。

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

### DN 分片主备切换

`switch_shard` 位于动态 OpenAPI 目录并分类为 `DANGEROUS`。先用 `get_instance` 获取组件，
选择将要升主的 Standby DN，再查询运行时 Schema：

```json
{
  "operation": "switch_shard",
  "request": {
    "instance_id": "<instance-id>",
    "body": {
      "shards": [
        {
          "node_id": "<standby-node-id>",
          "component_id": "<standby-component-id>"
        }
      ]
    }
  },
  "confirm": true
}
```

`component_id` 来自 `get_instance` 返回的 `nodes[].components[]`，例如 `dn_6002`。调用
`invoke_dangerous_openapi` 后，用 `wait_job` 跟踪返回的任务。成功后若实例进入 `BACKING UP`，
继续查询到 `ACTIVE`，再用 `get_instance` 验证角色。
单副本不支持该操作；同一分片一次只能选择一个新的主节点。

### EIP 分配与绑定

`list_binded_eips` 和 `attach_eip` 属于 GaussDB OpenAPI；后者只接受已存在的公网地址和
`public_ip_id`。无可用 EIP 时，先通过华为云 VPC/EIP `CreatePublicip`（例如
`hcloud EIP CreatePublicip`）创建，再调用 `attach_eip`，最后用 `list_binded_eips` 验证。

## 跨服务工具

购买前报价不是 GaussDB OpenAPI。通过独立的 BSS/计费连接器调用：

| 任务 | BSS 操作 | 约束 |
|---|---|---|
| 按需询价 | `ListOnDemandResourceRatings` | 商品编码和度量单位来自 BSS 目录 |
| 包年/包月询价 | `ListRateOnPeriodDetail` | 按真实购买期限查询 |
| 账户余额 | `ShowCustomerAccountBalances` | 客户自身凭证及 `billing:balance:view` |

没有 BSS 连接器或权限时停止自动报价，不通过 `invoke_read_openapi` 调用跨服务 API。

## 常见错误

✅ 正确：先用 `discover_create_options` 得到 `spec_code` 和 AZ，再构造创建配置。

❌ 错误：把北京四查询到的规格码用于贵阳一，或假设所有区域支持同样的数据库版本。

✅ 正确：将 `get_backup_policy` 返回的差量周期整数传给 `configure_backup_policy`。

❌ 错误：把 `differential_period` 当作星期字符串，或将云端历史拼写
`differential_priod` 传给写工具。

✅ 正确：删除标签前先 `describe_openapi_operation`；删除标签的 `instance_id` 和 `key` 位于顶层。

❌ 错误：照搬添加标签的 `body.tags` 数组形态调用删除标签。
