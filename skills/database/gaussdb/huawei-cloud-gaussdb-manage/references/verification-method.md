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

## 2. MCP 本地启动验证

```bash
uv sync --all-packages
uv run mcp-server-huaweicloud-gaussdb
```

通过 MCP 客户端完成 initialize 和 tools/list。成功标准：服务正常启动，返回 22 个工具，包含
`discover_create_options`、`update_instance_parameters` 和 `describe_openapi_operation`。

## 3. 凭证与权限验证

设置 `HUAWEICLOUD_MCP_READ_ONLY=true` 后：

1. 调用 `list_instances(limit=1)`。
2. 调用 `discover_create_options(limit=1)`。
3. 不显式提供 Project ID，确认响应中的项目与 region 匹配。

成功标准：没有 `MCP_CREDENTIAL_ERROR`；实例列表可以为空；发现工具返回项目上下文和实时创建
选项。若缺少 IAM/VPC 权限，错误应清楚指出失败阶段，且不包含凭证值。

## 4. 只读功能验证

在账号中存在测试实例时执行：

1. `list_instances` → `get_instance`，核对 ID、名称、状态、版本和 node IDs。
2. `list_flavors`，核对规格来自当前区域并带 AZ 可售信息。
3. `get_instance_parameters(modifiable_only=true, limit=5)`，核对 `readonly`、
   `restart_required`、`value_range` 和风险信息。
4. `list_backups(limit=5)` 与 `get_backup_policy`。
5. `list_openapi_operations(query="tag")` → `describe_openapi_operation`。

成功标准：所有响应均为结构化对象；分页字段可继续读取；没有把其他区域的静态数据混入结果。

## 5. 安全护栏验证

1. 保持只读模式调用任一 WRITE 工具，确认被阻断。
2. `delete_instance(confirm=false)` 必须返回确认要求，不能发出删除请求。
3. 用受保护的 ID、名称或标签测试删除，确认二次保护检查生效。
4. 对只读、未知和高风险参数分别测试更新预览，确认未知/只读失败关闭，高风险要求确认。
5. 检查 stderr 和 JSONL 审计：不得出现 AK、SK、SecurityToken 或数据库密码。

## 6. 可选云端写操作验证

只有用户明确授权、使用专用测试项目并接受费用时执行：

1. 用实时发现结果创建按需测试实例。
2. 轮询 `get_job` 并用 `get_instance` 验证可用。
3. 创建手工备份，修改一个可恢复的低风险参数，再恢复原值。
4. 验证规格/容量或备份策略写操作时，记录前后值和任务 ID。
5. 用户明确授权清理后删除测试实例，轮询到完成，并用 `list_instances` 确认不存在。

云端验证报告至少记录区域、MCP/SDK 版本、工具输入的脱敏摘要、请求 ID、任务 ID、状态、
验证结果和清理结果。创建未成功时不得把区域资源不足误判为 MCP 逻辑缺陷。

## 7. 安全扫描

从 Skill 包根目录执行：

```bash
rg -n --hidden -i '(ak|sk|access[_-]?key|secret[_-]?key|securitytoken)[[:space:]]*[:=][[:space:]]*[A-Za-z0-9/+_-]{12,}' .
```

成功标准：没有真实凭证命中。文档中的变量名和占位符可以出现，但不得包含可用值。
