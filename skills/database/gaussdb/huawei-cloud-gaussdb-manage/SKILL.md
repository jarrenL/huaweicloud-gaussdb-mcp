---
name: huawei-cloud-gaussdb-manage
description: |
  通过 Huawei Cloud GaussDB MCP Server 管理 GaussDB（openGauss）控制面，完成购买前选型与询价编排、实例生命周期、备份、参数、慢 SQL 和 DN 主备切换。适用于明确要求使用 MCP 管理华为云 GaussDB 的场景。NOT for: GaussDB(for MySQL)、直接 hcloud/KooCLI 运维、Terraform 建库、库内 SQL/DDL 或通用验收手册；这些场景分别路由到 huawei-gaussdb（或 huawei-cloud-gaussdb-instance-management）、对应 IaC Skill、huaweicloud-gaussdb-data 或专门验收 Skill。
metadata:
  tags: [huawei-cloud, gaussdb, database, mcp, operations]
  version: "1.2.0"
---

# 华为云 GaussDB 管理

## 概述

使用 `mcp-server-huaweicloud-gaussdb` 管理华为云 GaussDB。该 Skill 只覆盖 GaussDB，
不处理 DRS。

调用链为：用户 → Agent/MCP 客户端 → GaussDB MCP Server → 安全护栏与审计 →
GaussDB、VPC 和 IAM OpenAPI。Skill 不保存会话状态；区域、实例 ID、任务 ID和本次选择的
配置都必须从当前上下文或实时工具响应中显式取得。

适用场景：

- 购买前实时选型，调用外部 BSS 能力取得按需或包周期报价并检查余额。
- 查询实例、拓扑、版本、规格、网络和运行状态。
- 创建集中式或分布式 GaussDB，选择基础版、企业版或生态版。
- 创建或查询备份，修改备份策略。
- 变更规格、扩容存储/CN/DN、重启实例。
- 查询并安全修改实例参数，分析慢 SQL。
- 对集中式高可用实例执行 DN 分片主备切换并验证结果。
- 通过动态 OpenAPI 目录访问没有专用场景工具的公开接口。

典型用例：

- “列出北京四的 GaussDB 实例，并告诉我哪些正在运行。”
- “查询贵阳一可创建的基础版分布式规格，先不要创建。”
- “比较开发、生产和大容量三档方案，并查询当前账号的实际价格。”
- “创建一个开发测试用的集中式单副本实例。”
- “先检查 `max_connections` 是否可改，再给我变更预览。”
- “把集中式实例的备用 DN 升为主节点，先给我切换计划。”
- “分析这个实例最近一小时的慢 SQL，并按平均耗时排序。”

## 能力边界与路由

只在用户明确要求通过本仓库的 MCP 管理 **GaussDB（openGauss）控制面**时使用本 Skill。
多个 GaussDB Skill 同时安装时，按以下规则选择，不能对同一次写操作同时调用两套实现：

| 用户意图 | 路由 |
|---|---|
| MCP 方式管理 GaussDB（openGauss），含动态 OpenAPI、参数安全、慢 SQL、主备切换 | 本 Skill |
| 直接使用 hcloud/KooCLI，或同时管理 GaussDB(for MySQL) 和 GaussDB（openGauss） | `huawei-gaussdb` 或 `huawei-cloud-gaussdb-instance-management` |
| 库内查询、写入、DDL、账号或元数据操作 | 已安装时使用 `huaweicloud-gaussdb-data` 数据面 MCP |
| Terraform/IaC 创建与销毁 | 对应 GaussDB IaC Skill |
| 独立运维手册、上线验收或安全基线报告 | 专门的运维/验收 Skill |

本 Skill 不把 GaussDB(for MySQL) 当作 GaussDB（openGauss）的部署形态，也不通过管控面
OpenAPI 执行任意 SQL。找不到目标路由时，说明缺少的连接器或 Skill，不把请求静默改成其他产品。

## 前置条件

1. Python 3.10+ 和 `uv` 已安装；MCP Server 至少为 `0.4.0`。以运行时
   `initialize` 和 `tools/list` 返回的版本与工具清单为准，不把文档中的工具数量当作固定上限。
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
6. 响应包含 `job_id` 时优先调用 `wait_job`，在有界超时内跟踪到成功、失败或明确的非终态；
   超时后使用同一 `job_id` 继续等待，不要重复提交写操作，也不要把“请求已受理”当作任务完成。
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

### 购买前选型与询价

1. 收集区域、产品类型、集中式/分布式、部署形态、版本、CPU/内存、存储类型与容量、节点数、
   计费模式、购买时长、是否需要 EIP/备份以及预算上限。缺少关键输入时停在候选方案阶段。
2. 调用 `discover_create_options` 和 `list_flavors` 获取当前区域的实时可售组合，不复用其他区域
   的规格码或价格。
3. 给出三档候选，但必须以实时可售性为准：开发测试优先 `single`，生产高可用优先 `triset`，
   大容量或横向扩展场景比较 `combined` / `hws` 分布式方案。
4. GaussDB MCP 不直接暴露 BSS。通过已连接的华为云 BSS/计费工具分别调用
   `ListOnDemandResourceRatings`（按需）、`ListRateOnPeriodDetail`（包周期）和
   `ShowCustomerAccountBalances`（账户余额）。请求字段和商品编码必须来自 BSS 实时查询或价格
   计算器，不能从 GaussDB `spec_code` 猜测。
5. 将计算节点、存储、备份、公网和其他计费项分开列出，再给出三档总价、币种、价格单位、
   优惠口径和查询时间。只有返回单位明确为小时价时，才可按用户认可的月小时数换算月成本，
   并把该小时数标为估算假设。
6. 余额查询失败、账号无 BSS 权限或商品编码无法映射时，返回“未取得权威报价”，并提供价格
   计算器或人工确认路径；不得编造金额，也不得据此自动创建实例。

详细流程、权限边界和结果模板见
[references/purchase-estimation.md](references/purchase-estimation.md)。

### 参数修改

1. 调用 `get_instance_parameters(instance_id, name, modifiable_only=true)` 获取当前实例的实时
   参数元数据。
2. 只提交云端明确标记可修改且通过类型和值域校验的参数。先展示旧值、新值、风险等级和是否
   需要重启。
3. 对需要重启或被标记为敏感的参数，先获取工具预览；用户确认后再以 `confirm=true` 调用
   `update_instance_parameters`。
4. 修改后再次查询参数确认生效。需要重启时单独说明影响并取得重启授权。

### 主备切换与容灾

1. 先用 `get_instance` 读取实例和组件，只允许状态正常、具备主备 DN 的实例进入切换计划；
   单副本不支持 DN 主备切换。
2. 从目标备用 DN 的组件中取得真实 `node_id`、`component_id`、`role` 和 `distributed_id`。
   每个分片只选择一个待升主的备用 DN，不凭名称猜组件 ID。
3. 调用 `describe_openapi_operation(operation="switch_shard")` 复核运行时 Schema。当前请求形态为
   `{"instance_id":"...","body":{"shards":[{"node_id":"...","component_id":"dn_..."}]}}`。
4. 展示目标实例、分片、当前主节点、待升主节点、连接中断影响和验证方案。取得对这组精确组件
   的显式确认后，调用 `invoke_dangerous_openapi(operation="switch_shard", request=..., confirm=true)`。
5. 返回 `job_id` 后调用 `wait_job` 跟踪到终态；任务名通常为 `SWITCHDN`，但以云端响应为准。
6. 任务成功后，实例可能因自动备份进入 `BACKING UP`。继续用 `get_instance` 等到 `ACTIVE`，
   在此之前不提交下一项写操作。
7. 再次调用 `get_instance`，确认目标组件已成为 Primary、原主节点变为 Standby，并核对
   `distributed_id` 的分片映射。不要假设该字段一定变化或一定保持不变。

切换属于 `DANGEROUS`，期间连接可能中断。失败后先读取任务和实例状态，不自动重试切换。

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

### EIP 创建与绑定

1. 用 `list_openapi_operations(query="eip")` 和 `describe_openapi_operation` 发现
   `list_binded_eips`、`attach_eip` 的实时请求结构。
2. `attach_eip` 只绑定或解绑已有 EIP。没有可用 EIP 时，路由到华为云 VPC/EIP 服务的
   `CreatePublicip`（例如 `hcloud EIP CreatePublicip`）创建；不得把 EIP 创建请求发给 GaussDB。
3. 将新建接口返回的公网地址和公网 IP ID 连同实例、节点传给 `attach_eip`。绑定属于危险操作，
   核对精确资源并取得确认后调用，再用 `list_binded_eips` 验证。

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
| 慢 SQL | `analyze_slow_sql`（毫秒时间戳或带时区 ISO 8601） | READ/敏感数据 |
| 异步任务 | `get_job`, `wait_job` | READ |
| DN 主备切换 | `describe_openapi_operation` → `invoke_dangerous_openapi`（`switch_shard`） | DANGEROUS |
| 删除实例 | `delete_instance` | DANGEROUS |

全部工具、关键参数和调用约束见
[references/related-tools.md](references/related-tools.md)。

## 参数确认

| 参数 | 必需 | 默认值 | 确认规则 |
|---|---:|---|---|
| 区域 | 是 | 凭证中的 `region` | 每次跨区域操作都显式说明 |
| 实例 ID | 实例操作必需 | 无 | 写操作前通过实时查询核对名称和状态 |
| 产品类型 | 创建时必需 | `basic` | 从 `basic` / `enterprise` / `ecology` 中选择 |
| 高可用模式 | 创建时必需 | `centralization_standard` | 分布式使用 `enterprise` 创建模式 |
| 部署形态 | 创建时必需 | 由发现工具推导 | 只使用实时可用组合 |
| 版本 | 创建/规格查询可选 | 云端返回值 | 不假设每个区域都有相同版本 |
| 规格 | 创建/规格变更必需 | 无 | 使用实时 `spec_code`，禁止写死 |
| 计费模式 | 创建/变更必需 | 不推断 | 包周期和自动支付必须明确授权 |
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
- [MCP 工具参考](references/related-tools.md)：当前场景/目录工具与关键参数。
- [购买前选型与询价](references/purchase-estimation.md)：BSS 路由、三档方案和预算输出。
- [验证方法](references/verification-method.md)：本地与云端验证步骤。
- [验收标准](references/acceptance-criteria.md)：功能、错误处理和安全通过条件。

## 注意事项

- 当前版本不包含 DRS。
- 当前 MCP 只管理 GaussDB（openGauss）控制面；数据面 SQL/DDL 路由到
  `huaweicloud-gaussdb-data`（若已安装），GaussDB(for MySQL) 路由到对应 Skill。
- 公开 OpenAPI 目录随安装的华为云 SDK 变化，先查询目录再调用。
- `logger` 的查询可见不等于公开接口可以创建，禁止静默转换为 `triset`。
- 不在 Skill、示例、日志或回复中保存真实 AK/SK、SecurityToken、数据库密码或完整慢 SQL。
- 包周期退订、恢复、主备切换、升级和删除属于危险操作，必须核对精确资源并显式确认。
