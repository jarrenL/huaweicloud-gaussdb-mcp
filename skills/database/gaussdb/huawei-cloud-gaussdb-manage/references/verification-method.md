# 验证方法

## 概述

验证分为静态结构、本地启动、凭证与权限、只读功能、安全护栏和可选云端写操作六层。
默认只执行不会产生费用和资源变更的步骤。

## 1. 静态结构验证

在 Skill 包根目录执行：

```bash
python3 scripts/validate-skill.py
```

成功标准：退出码为 0，Frontmatter、目录名、章节、引用文件、大小和敏感信息检查通过。

再检查：

- `name` 与目录名完全一致。
- `tags` 不超过 5 个。
- 所有 `references/*.md` 都以一级标题开头。
- SKILL.md 中的相对链接全部存在。
- 单个 SKILL.md 少于 500 行，整个 Skill 包小于 5 MiB。

## 2. 运行时冒烟验证

从 MCP 仓库根目录执行：

```bash
uv run --directory server/mcp_server_gaussdb python \
  "$PWD/skills/database/gaussdb/huawei-cloud-gaussdb-manage/scripts/smoke.py" \
  -- uv run --directory "$PWD/server/mcp_server_gaussdb" mcp_server_gaussdb
```

脚本强制子进程使用 `HUAWEICLOUD_MCP_READ_ONLY=true`，并依次完成：

1. MCP `initialize`。
2. `tools/list` 和关键工具存在性检查。
3. `list_instances(limit=1)` 凭证与区域联通检查。
4. 对虚构实例调用 `restart_instance(confirm=false)`，确认在访问云端前返回
   `MCP_READ_ONLY`。

脚本只输出服务名、版本、工具数量、返回条目数和护栏错误码，不输出资源详情或凭证。只检查
服务注册、不访问云端时增加 `--skip-cloud`。从独立 Skill 目录运行时，可使用：

```bash
uv run --with 'mcp>=1,<3' python scripts/smoke.py -- \
  uvx mcp-server-huaweicloud-gaussdb
```

只有 PyPI 已发布服务及 core 包时才能使用默认 `uvx` 方式；发布前使用源码工作区命令。

## 3. MCP 手动启动验证

```bash
uv sync --directory server/mcp_server_gaussdb --frozen
uv run --directory server/mcp_server_gaussdb mcp_server_gaussdb
```

通过 MCP 客户端完成 initialize 和 tools/list。成功标准：服务正常启动，返回不少于 25 个
工具，包含 `discover_create_options`、`update_instance_parameters`、
`describe_openapi_operation` 和 `invoke_dangerous_openapi`。新增兼容工具不应导致验证失败。

## 4. 凭证与权限验证

设置 `HUAWEICLOUD_MCP_READ_ONLY=true` 后：

1. 调用 `list_instances(limit=1)`。
2. 调用 `discover_create_options(limit=1)`。
3. 不显式提供 Project ID，确认响应中的项目与 region 匹配。

成功标准：没有 `MCP_CREDENTIAL_ERROR`；实例列表可以为空；发现工具返回项目上下文和实时创建
选项。若缺少 IAM/VPC 权限，错误应清楚指出失败阶段，且不包含凭证值。

## 5. 只读功能验证

在账号中存在测试实例时执行：

1. `list_instances` → `get_instance`，核对 ID、名称、状态、版本和 node IDs。
2. `list_flavors`，核对规格来自当前区域并带 AZ 可售信息。
3. `get_instance_parameters(modifiable_only=true, limit=5)`，核对 `readonly`、
   `restart_required`、`value_range` 和风险信息。
4. `list_backups(limit=5)` 与 `get_backup_policy`。
5. `list_openapi_operations(query="tag")` → `describe_openapi_operation`。
6. `describe_openapi_operation(operation="switch_shard")`，确认风险是 `DANGEROUS`，且请求要求
   `instance_id` 和 `body.shards[].node_id/component_id`。

7. 有 CES 权限时，调用 `list_monitoring_metrics`，复制实际返回的指标和完整维度查询最近一小时。
   核对单位、时间窗、采样数量、摘要及 `no_data`；跨节点/组件时不复用错误维度。

成功标准：所有响应均为结构化对象；分页字段可继续读取；没有把其他区域的静态数据混入结果。

## 6. 安全护栏验证

1. 保持只读模式调用任一 WRITE 工具，确认被阻断。
2. `delete_instance(confirm=false)` 必须返回确认要求，不能发出删除请求。
3. 用受保护的 ID、名称或标签测试删除，确认二次保护检查生效。
4. 对只读、未知和高风险参数分别测试更新预览，确认未知/只读失败关闭，高风险要求确认。
5. 检查 stderr 和 JSONL 审计：不得出现 AK、SK、SecurityToken 或数据库密码。
6. 保持只读模式调用 `restart_instance`，确认在发送云请求前返回 `MCP_READ_ONLY`。

## 7. 可选云端写操作验证

只有用户明确授权、使用专用测试项目并接受费用时执行：

1. 用实时发现结果创建按需测试实例。
2. 用 `wait_job` 轮询到终态，并用 `get_instance` 验证可用。
3. 创建手工备份，修改一个可恢复的低风险参数，再恢复原值。
4. 验证规格/容量或备份策略写操作时，记录前后值和任务 ID。
5. 用户明确授权清理后删除测试实例，轮询到完成，并用 `list_instances` 确认不存在。

主备切换验证只在已有专用高可用测试实例、用户明确授权连接中断时执行：从
`get_instance.nodes[].components[]` 选择 Standby DN，调用 `switch_shard`，跟踪任务，再确认
Primary/Standby 角色互换。不能为了验收临时创建高成本实例。

云端验证报告至少记录区域、MCP/SDK 版本、工具输入的脱敏摘要、请求 ID、任务 ID、状态、
验证结果和清理结果。创建未成功时不得把区域资源不足误判为 MCP 逻辑缺陷。

## 8. 安全扫描

从 Skill 包根目录执行：

```bash
rg -n --hidden -i '(ak|sk|access[_-]?key|secret[_-]?key|securitytoken)[[:space:]]*[:=][[:space:]]*[A-Za-z0-9/+_-]{12,}' .
```

成功标准：没有真实凭证命中。文档中的变量名和占位符可以出现，但不得包含可用值。
