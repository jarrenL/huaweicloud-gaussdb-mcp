---
name: huawei-cloud-gaussdb-manage
description: |
  通过 Huawei Cloud GaussDB MCP Server 管理 GaussDB 实例。基于 MCP 0.3.7 的场景工具和 OpenAPI 目录，完成实例查询与创建、规格或容量变更、备份、参数调整、重启、慢 SQL 分析和删除。用户提到华为云 GaussDB、实例管理、数据库创建、备份、扩容、参数、慢 SQL 或 GaussDB OpenAPI 时使用。
metadata:
  tags: [huawei-cloud, gaussdb, database, mcp, operations]
  version: "1.0.0"
---

# Huawei Cloud GaussDB Management

## 概述

使用 `mcp-server-huaweicloud-gaussdb` 管理华为云 GaussDB。该 Skill 只覆盖 GaussDB，
不处理 DRS。

调用链为：用户 → Agent/MCP 客户端 → GaussDB MCP Server → 安全护栏与审计 →
GaussDB、VPC 和 IAM OpenAPI。Skill 不保存会话状态；区域、实例 ID、任务 ID和本次选择的
配置都必须从当前上下文或实时工具响应中显式取得。

适用场景：

- 查询实例、拓扑、版本、规格、网络和运行状态。
- 创建集中式或分布式 GaussDB，选择基础版、企业版或生态版。
- 创建或查询备份，修改备份策略。
- 变更规格、扩容存储/CN/DN、重启实例。
- 查询并安全修改实例参数，分析慢 SQL。
- 通过动态 OpenAPI 目录访问没有专用场景工具的公开接口。

典型用例：

- “列出北京四的 GaussDB 实例，并告诉我哪些正在运行。”
- “查询贵阳一可创建的基础版分布式规格，先不要创建。”
- “创建一个开发测试用的集中式单副本实例。”
- “先检查 `max_connections` 是否可改，再给我变更预览。”
- “分析这个实例最近一小时的慢 SQL，并按平均耗时排序。”

## 前置条件

1. Python 3.10+ 和 `uv` 已安装；MCP Server 版本为 `0.3.7` 或兼容版本。
2. MCP 客户端已经注册 `huaweicloud-gaussdb` 服务。安装和注册方法见
   [references/mcp-installation-guide.md](references/mcp-installation-guide.md)。
3. 使用独立 IAM 用户或临时凭证，并按实际操作授予最小权限。需要的系统策略、授权项和
   权限失败处理见 [references/iam-policies.md](references/iam-policies.md)。
4. 不要求用户在对话中粘贴 AK/SK。服务按字段依次读取显式环境变量、MCP 凭证文件、
   `~/.config/huaweicloud/credentials.json` 中的 devkit 凭证；Project ID 缺省时由 IAM
   按区域自动发现。
5. 首次接入设置 `HUAWEICLOUD_MCP_READ_ONLY=true`，先完成只读验证。

如果凭证或权限校验失败，只说明缺少的配置项或授权项，不输出凭证、密码、SecurityToken、
完整 SQL 文本或其他敏感内容。

## 工作流

### 通用流程

1. 从用户请求中确定区域、目标资源、期望结果和是否允许写操作。不要复用其他会话的资源 ID。
2. 先调用只读工具建立当前事实：实例操作先用 `list_instances` / `get_instance`，创建先用
   `discover_create_options`，参数修改先用 `get_instance_parameters`。
3. 只采用实时返回的版本、部署形态、规格码、可用区、VPC、子网和安全组；不得把某一区域的
   数量、规格码或可售状态写死。
4. 对写操作展示目标资源、最终参数、影响、是否中断连接、是否产生费用和回滚方式。用户当前
   指令未明确授权这组具体参数时，在实际写调用前取得确认。
5. 调用专用场景工具。只有没有专用工具时，才执行 OpenAPI 目录流程。
6. 响应包含 `job_id` 时调用 `get_job` 跟踪到成功、失败或明确的非终态；不要把“请求已受理”
   当作任务完成。
7. 用对应只读工具复查云端状态，并输出结构化结果、未决风险和任务 ID。

### 创建实例

1. 调用 `discover_create_options`，显式传入用户选择的 `ha_mode`、`deployment_mode`、
   `product_type` 和 `version`；用户没有选择时展示实时可用项和成本/可用性差异。
2. 从 `recommended_configuration` 和实时返回值构造请求。密码只通过客户端支持的安全输入方式
   注入，不在回复、日志或报告中回显；没有安全输入能力时停在创建计划阶段。
3. 集中式支持 `single`、`triset`；`logger` 可以被发现，但当前公开 v3.2 创建请求不能唯一
   表达该形态，工具会拒绝直接创建。基础版分布式使用 `combined`，企业版/生态版分布式使用
   `hws`，最终可售性以当前区域和租户的云端校验为准。
4. 显示名称、区域、版本、产品类型、部署形态、规格、节点/副本、存储、AZ、网络、计费方式和
   预计影响，取得具体授权后调用 `create_instance`。
5. 跟踪创建任务，再用 `get_instance` 验证实例状态。测试实例用完后，仅在用户明确授权删除该
   实例时执行删除流程。

### 参数修改

1. 调用 `get_instance_parameters(instance_id, name, modifiable_only=true)` 获取当前实例的实时
   参数元数据。
2. 只提交云端明确标记可修改且通过类型和值域校验的参数。先展示旧值、新值、风险等级和是否
   需要重启。
3. 对需要重启或被标记为敏感的参数，先获取工具预览；用户确认后再以 `confirm=true` 调用
   `update_instance_parameters`。
4. 修改后再次查询参数确认生效。需要重启时单独说明影响并取得重启授权。

### 删除或其他危险操作

1. 用 `get_instance` 重新读取目标实例，核对 ID、名称、标签、计费方式、备份和保护规则。
2. 展示不可逆影响并取得对该精确资源的明确确认。
3. 调用 `delete_instance(..., confirm=true)`；通用危险接口使用
   `invoke_dangerous_openapi(..., confirm=true)`。
4. 跟踪任务并重新查询，直到删除完成或返回可解释的终态。

### OpenAPI 目录流程

1. 用 `list_openapi_operations` 按名称、分类或风险查找操作。
2. 用 `describe_openapi_operation` 获取完整请求结构和示例，禁止凭记忆猜字段。
3. 按返回的风险级别选择 `invoke_read_openapi`、`invoke_write_openapi` 或
   `invoke_dangerous_openapi`。
4. `direct_invoke_supported=false` 时改用指定的专用工具，不得绕过场景工具的校验。

## 核心命令（MCP 工具）

优先使用以下专用工具：

| 任务 | 工具 | 风险 |
|---|---|---|
| 查询实例 | `list_instances`, `get_instance` | READ |
| 创建选型 | `discover_create_options`, `list_flavors` | READ |
| 创建实例 | `create_instance` | WRITE/计费 |
| 规格与容量 | `resize_instance`, `expand_instance` | WRITE/可能中断或计费 |
| 重启 | `restart_instance` | WRITE/中断连接 |
| 参数管理 | `get_instance_parameters`, `update_instance_parameters` | READ/WRITE |
| 备份 | `list_backups`, `create_manual_backup` | READ/WRITE |
| 备份策略 | `get_backup_policy`, `configure_backup_policy` | READ/WRITE |
| 慢 SQL | `analyze_slow_sql` | READ/敏感数据 |
| 异步任务 | `get_job` | READ |
| 删除实例 | `delete_instance` | DANGEROUS |

全部工具、关键参数和调用约束见
[references/related-tools.md](references/related-tools.md)。

## 参数确认

| 参数 | 必需 | 默认值 | 确认规则 |
|---|---:|---|---|
| Region | 是 | 凭证中的 `region` | 每次跨区域操作都显式说明 |
| Instance ID | 实例操作必需 | 无 | 写操作前通过实时查询核对名称和状态 |
| Product type | 创建时必需 | `basic` | 从 `basic` / `enterprise` / `ecology` 中选择 |
| HA mode | 创建时必需 | `centralization_standard` | 分布式使用 `enterprise` 创建模式 |
| Deployment mode | 创建时必需 | 由发现工具推导 | 只使用实时可用组合 |
| Version | 创建/规格查询可选 | 云端返回值 | 不假设每个区域都有相同版本 |
| Flavor | 创建/规格变更必需 | 无 | 使用实时 `spec_code`，禁止写死 |
| Billing | 创建/变更必需 | 不推断 | 包周期和自动支付必须明确授权 |
| `confirm` | 受保护写操作必需 | `false` | DANGEROUS 必须为 `true`；普通写操作按护栏结果处理 |

备份策略中的 `period` 是星期列表，例如 `1,3,5`；`differential_period` 是分钟间隔，只能为
`15`、`30`、`60`、`180`、`360`、`720` 或 `1440`。不要混淆二者。

## 输出格式

写操作前输出计划：

```text
状态：待确认
区域：<region>
目标：<instance-name> (<instance-id>)
操作：<operation>
参数：<脱敏后的关键参数>
影响：<连接、可用性、费用、不可逆性>
验证：<完成后调用的只读工具>
```

执行后输出结果：

```text
状态：成功 | 失败 | 处理中
操作：<operation>
资源：<instance-name> (<instance-id>)
任务：<job-id 或 order-id>
云端验证：<关键状态与时间>
后续动作：<仅列真实需要的动作>
```

进度可使用 `⏳ 进行中`、`✅ 已完成`、`○ 待执行`。保留工具的 JSON 作为机器可读证据，
面向用户的摘要必须脱敏。

## 验证方法

按 [references/verification-method.md](references/verification-method.md) 完成安装、配置、
只读功能、写操作护栏和安全扫描验证。验收口径见
[references/acceptance-criteria.md](references/acceptance-criteria.md)。

## 最佳实践

- 默认从 READ 工具开始；生产资源先做备份检查，再进行变更。
- 创建、规格、版本和部署形态全部实时发现；同一产品在不同区域和租户可能不同。
- 有专用工具时不用通用 OpenAPI 通道，保留参数校验、保护名单和二次确认。
- 慢 SQL 文本可能包含业务数据，只返回诊断所需字段并遵循最小披露原则。
- 对轮询设置合理停止条件；失败时返回云端错误码、请求 ID 和下一步，不进行无限重试。

## 参考文档

- [MCP 安装与配置](references/mcp-installation-guide.md)：安装、客户端注册、凭证优先级和热加载。
- [IAM 权限策略](references/iam-policies.md)：只读、写入、危险操作及 Project 自动发现权限。
- [MCP 工具参考](references/related-tools.md)：22 个场景/目录工具与关键参数。
- [验证方法](references/verification-method.md)：本地与云端验证步骤。
- [验收标准](references/acceptance-criteria.md)：功能、错误处理和安全通过条件。

## 注意事项

- 当前版本不包含 DRS。
- 公开 OpenAPI 目录随安装的华为云 SDK 变化，先查询目录再调用。
- `logger` 的查询可见不等于公开接口可以创建，禁止静默转换为 `triset`。
- 不在 Skill、示例、日志或回复中保存真实 AK/SK、SecurityToken、数据库密码或完整慢 SQL。
- 包周期退订、恢复、主备切换、升级和删除属于危险操作，必须核对精确资源并显式确认。
