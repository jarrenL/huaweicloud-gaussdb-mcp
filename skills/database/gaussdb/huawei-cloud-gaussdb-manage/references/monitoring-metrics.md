# GaussDB 监控指标参考

本文解释一次基础版集中式单副本实例实测取得的 58 项 CES 指标，包含实例层 7 项、节点层
16 项和组件层 35 项。清单用于理解指标，实际可用项由区域、版本、部署形态、主备角色和
采集状态共同决定。MCP 通过实时发现访问指标，支持查询本表之外的云端指标。

指标 ID、层级和单位以 CES 返回为准；产品定义参见
[GaussDB 官方监控指标文档](https://support.huaweicloud.com/usermanual-gaussdb/gaussdb_01_238.html)。
以下解释为便于诊断的简述，不替代产品对统计口径、适用角色和采集周期的定义。

## 层级与查询方法

命名空间为 `SYS.GAUSSDBV5`。

| 层级 | 完整维度 | 发现参数 |
|---|---|---|
| 实例 | `gaussdbv5_instance_id` | `instance_id` |
| 节点 | 实例维度 + `gaussdbv5_node_id` | `instance_id` + 真实 `node_id` |
| 组件 | 实例、节点维度 + `gaussdbv5_component_id` | `instance_id` + 真实 `node_id` + DN/CN `component_id` |

先用 `get_instance` 获取拓扑，再分别调用 `list_monitoring_metrics`，每个层级独立按 marker
分页。仅传实例 ID 时只查询实例层，星号不会自动展开节点或组件。选中指标后，保留返回条目的
完整 `dimensions`，直接传给 `query_monitoring_metrics`；工具会归一维度顺序。

## 实例层：7 项

| 指标 ID | 含义 | 单位 |
|---|---|---|
| `rds005_instance_disk_used_size` | 实例数据磁盘已使用的容量 | GB |
| `rds006_instance_disk_total_size` | 实例数据磁盘的总容量 | GB |
| `rds007_instance_disk_usage` | 实例数据磁盘已用容量占总容量的比例 | % |
| `rds035_buffer_hit_ratio` | 数据库 Buffer 的命中比例，用于观察缓存效果 | % |
| `rds036_deadlocks` | 采集周期内新增的事务死锁次数 | Count |
| `rds048_P80` | SQL 响应时间的第 80 百分位，反映大部分请求的耗时 | us |
| `rds049_P95` | SQL 响应时间的第 95 百分位，用于观察尾部耗时 | us |

## 节点层：16 项

| 指标 ID | 含义 | 单位 |
|---|---|---|
| `rds001_cpu_util` | 当前节点的 CPU 占用比例 | % |
| `rds002_mem_util` | 当前节点的内存占用比例 | % |
| `rds003_bytes_in` | 官方名称为“数据写入量”，统计口径为对应 VM 的网络发送字节速率 | byte/s |
| `rds004_bytes_out` | 官方名称为“数据传出量”，统计口径为对应 VM 的网络接收字节速率 | byte/s |
| `rds014_iops` | 节点数据磁盘每秒完成的读写次数 | Count/s |
| `io_bandwidth_usage` | 当前磁盘 IO 带宽相对最大带宽的占用比例 | % |
| `iops_usage` | 当前 IOPS 相对磁盘最大 IOPS 的占用比例 | % |
| `rds016_disk_write_throughput` | 节点数据磁盘每秒写入的数据量 | byte/s |
| `rds017_disk_read_throughput` | 节点数据磁盘每秒读取的数据量 | byte/s |
| `rds020_avg_disk_ms_per_write` | 磁盘单次写入的平均耗时 | ms |
| `rds021_avg_disk_ms_per_read` | 磁盘单次读取的平均耗时 | ms |
| `rds068_swap_used_ratio` | 操作系统交换内存的使用比例 | % |
| `rds069_swap_total_size` | 操作系统交换内存的总容量 | MB |
| `rds084_sys_database_size` | 系统数据库 postgres 的大小 | byte |
| `rds085_user_database_size` | 所有用户数据库的大小总和 | byte |
| `retrans_rate` | TCP 数据包的重传比例，用于辅助观察网络质量 | % |

网络指标的名称与方向按官方口径列出，不根据 `in` / `out` 后缀自行推断业务读写流量。

## 组件层：35 项

| 指标 ID | 含义 | 单位 |
|---|---|---|
| `rds008_disk_used_size` | 对应组件上报的数据磁盘已用容量 | GB |
| `rds009_disk_total_size` | 对应组件上报的数据磁盘总容量 | GB |
| `rds010_disk_usage` | 对应组件上报的数据磁盘使用比例 | % |
| `rds028_standby_delay` | 分片内主备 redo 进度的字节差距 | byte |
| `rds030_wait_ratio` | 锁等待会话占活跃工作会话的比例 | % |
| `rds031_active_ratio` | 活跃工作会话占总会话数的比例 | % |
| `rds041_resp_avg` | 用户事务的平均响应耗时 | us |
| `rds042_rollback_ratio` | 用户回滚事务占用户提交与回滚事务总数的比例 | % |
| `rds043_bg_rollback_ratio` | 后台回滚事务占后台提交与回滚事务总数的比例 | % |
| `rds047_ddl_dcl_ratio` | Query 层 DDL 与 DCL 数量之和占 DDL、DCL、DML 总数的比例 | % |
| `rds050_ckpt_delay` | 信息同步到磁盘过程中尚待落盘的数据量 | byte |
| `rds053_online_session` | 当前在线的会话数量 | Count |
| `rds054_active_session` | 当前处于活跃工作状态的会话数量 | Count |
| `rds055_online_ratio` | 数据库上报的在线会话比例 | % |
| `rds060_long_running_transaction_exectime` | 当前最长事务已执行的时间 | s |
| `rds061_idle_in_transaction_num` | 事务处于空闲状态的连接数量 | Count |
| `rds062_slowquery_sys` | 指定周期内系统数据库的慢 SQL 数量 | Count |
| `rds063_slowquery_user` | 指定周期内用户数据库的慢 SQL 数量 | Count |
| `rds064_dynamic_used_memory` | 已使用的动态内存大小 | MB |
| `rds065_dynamic_used_memory_usage` | 动态内存的占用比例 | % |
| `rds066_replication_slot_wal_log_size` | 复制槽保留的 WAL 日志数据量 | byte |
| `rds070_thread_pool` | CN/DN 线程池的使用比例 | % |
| `rds071_locks_session` | 正在等待锁的会话数量 | Count |
| `rds078_inactive_replication_slot` | 非活跃的物理与逻辑复制槽数量 | Count |
| `rds080_xlog_num` | CN/DN 数据目录中的 XLOG 文件数量 | Count |
| `rds081_xlog_size` | CN/DN 数据目录中的 XLOG 总大小 | MB |
| `rds082_gaussv5_wait_session` | 当前处于等待状态的会话数量 | Count |
| `rds086_select_distribution` | SELECT 语句的分布比例 | % |
| `rds087_update_distribution` | UPDATE 语句的分布比例 | % |
| `rds088_insert_distribution` | INSERT 语句的分布比例 | % |
| `rds089_delete_distribution` | DELETE 语句的分布比例 | % |
| `rds096_process_used_memory` | CN/DN 进程已使用的内存大小 | MB |
| `rds097_2pc_transaction_prepare` | 两阶段事务中最长未决事务的存活时间 | s |
| `rds098_dn_instance_status` | DN 组件的状态编码，按状态枚举解释 | 无 |
| `rds113_bad_block_num` | 坏块数量；该释义按云端指标 ID 理解，详见下方说明 | Count |

`rds113_bad_block_num` 已在实测中返回采样值，但上述公开指标文档暂未列出该 ID。
其具体统计范围、采集周期和告警口径应向产品确认；不要仅凭名称推断坏块涉及的对象。

## 读数与诊断注意点

- `us` 表示微秒，`ms` 表示毫秒，`s` 表示秒；1 ms = 1000 us。
  `rds028_standby_delay` 和 `rds050_ckpt_delay` 的单位是字节，不能按时间延迟解读。
- 实例、节点和组件层的容量与占用可能覆盖同一批数据；不要直接相加，否则可能重复统计。
- `rds098_dn_instance_status` 是状态码：1 为正常 Primary，2 为正常 Standby，3 为正常
  Main Standby，4 为正常 Cascade Standby，10 为 Catchup，20 为备机连接正常但复制异常，
  21 为连接异常。按目标主备角色判断状态；查询时优先使用 `period=60`，查看最新点。
  聚合后的状态码平均数不表示一种有效状态。
- 新建实例可能还未上报全部指标。缺项时进行有界等待并重新发现；`no_data` 表示本次查询
  没有有效采样，不能当成零值或健康。检查采样时间，避免把过期数据当成当前状态。
- 计数、速率、比例和百分位的统计口径不同。P80/P95 的多点平均值不能作为整段时间的
  P80/P95；`aggregation_values_mean` 只是本次收到的聚合值的算术平均。
- 单次查询最多 20 条序列。保留完整维度，跨节点/组件时分别处理；时间范围较大时拆批、
  增大 period 或缩短时间窗。CPU、内存、磁盘、会话与慢 SQL 需结合业务负载和趋势分析，
  不从一次采样或固定通用阈值直接下结论。

工具参数、粒度与返回字段见 [MCP 工具参考](related-tools.md#ces-监控)。
