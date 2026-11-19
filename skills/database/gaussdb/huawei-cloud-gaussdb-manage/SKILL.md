---
name: huawei-cloud-gaussdb-manage
description: |
  通过 Huawei Cloud GaussDB MCP Server 管理 GaussDB（openGauss）控制面，完成购买前选型与询价编排、实例生命周期、备份、参数、慢 SQL、CES 监控诊断和包周期订单管理。适用于明确要求使用 MCP 管理华为云 GaussDB 的场景。NOT for: GaussDB(for MySQL)、直接 hcloud/KooCLI 运维、Terraform 建库、库内 SQL/DDL 或通用验收手册；这些场景分别路由到 huawei-gaussdb（或 huawei-cloud-gaussdb-instance-management）、对应 IaC Skill、huaweicloud-gaussdb-data 或专门验收 Skill。
metadata:
  tags: [huawei-cloud, gaussdb, database, mcp, operations]
  version: "1.6.0"
---

# 华为云 GaussDB 管理

## 概述

使用 `mcp_huaweicloud_gaussdb` 管理华为云 GaussDB。该 Skill 只覆盖 GaussDB，
不处理 DRS。

调用链为：用户 → Agent/MCP 客户端 → GaussDB MCP Server → 安全护栏与审计 →
GaussDB、BSS、CES、VPC 和 IAM 服务。Skill 不保存会话状态；区域、实例 ID、任务 ID和本次选择的
配置都必须从当前上下文或实时工具响应中显式取得。

主要能力包含：

- 购买前实时选型，调用外部 BSS 能力取得按需或包周期报价并检查余额。
- 查询实例、拓扑、版本、规格、网络和运行状态。
- 创建集中式或分布式 GaussDB，选择基础版、企业版或生态版。
- 创建或查询备份，修改备份策略。
- 查询 GaussDB 包周期订单金额和状态，按精确金额授权付款或取消待支付订单。
- 变更规格、扩容存储/CN/DN、重启实例。
- 查询并安全修改实例参数，分析慢 SQL。
- 通过 CES 查询 CPU、内存、存储、会话与事务等实时可发现的监控指标。

典型用例：

- “列出北京四的 GaussDB 实例，并告诉我哪些正在运行。”
- “查询贵阳一可创建的基础版分布式规格，先不要创建。”
- “比较开发、生产和大容量三档方案，并查询当前账号的实际价格。”
- “创建一个开发测试用的集中式单副本实例。”
- “先检查 `max_connections` 是否可改，再给我变更预览。”
- “分析这个实例最近一小时的慢 SQL，并按平均耗时排序。”
- “查询这个实例近半小时的 CPU、内存、存储和会话指标。”

## 能力边界与路由

只在用户明确要求通过本仓库的 MCP 管理 **GaussDB（openGauss）控制面**时使用本 Skill。
多个 GaussDB Skill 同时安装时，按以下规则选择，不能对同一次写操作同时调用两套实现：

| 用户意图 | 路由 |
|---|---|
| MCP 方式管理 GaussDB（openGauss），含实例管理、参数、备份和监控 | 本 Skill |
| 直接使用 hcloud/KooCLI，或同时管理 GaussDB(for MySQL) 和 GaussDB（openGauss） | `huawei-gaussdb` 或 `huawei-cloud-gaussdb-instance-management` |
| 库内查询、写入、DDL、账号或元数据操作 | 已安装时使用 `huaweicloud-gaussdb-data` 数据面 MCP |
| Terraform/IaC 创建与销毁 | 对应 GaussDB IaC Skill |
| 独立运维手册、上线验收或安全基线报告 | 专门的运维/验收 Skill |

本 Skill 不把 GaussDB(for MySQL) 当作 GaussDB（openGauss）的部署形态，也不在管控面执行任意 SQL。找不到目标路由时，说明缺少的连接器或 Skill，不把请求静默改成其他产品。

## 前置条件

1. Python 3.10+ 和 `uv` 已安装；使用 `mcp_huaweicloud_gaussdb` 的 `0.1.0` 或后续兼容版本。以运行时
   `initialize` 和 `tools/list` 返回的版本与工具清单为准，不把文档中的工具数量当作固定上限。
2. MCP 客户端已经注册 `huaweicloud-gaussdb` 服务。安装和注册方法见
   [references/mcp-installation-guide.md](references/mcp-installation-guide.md)。
3. 使用独立 IAM 用户或临时凭证，并按实际操作授予最小权限。需要的系统策略、授权项和
   权限失败处理见 [references/iam-policies.md](references/iam-policies.md)。
4. 不要求用户在对话中粘贴 AK/SK。服务按优先级从显式环境变量、MCP 凭证文件、
   `~/.config/huaweicloud/credentials.json` 中的 devkit 凭证成套读取 AK/SK/STS Token；
   Project ID 缺省时由 IAM
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
5. 调用匹配的专用工具。如果工具列表不支持所需操作，说明能力边界并停止执行。
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
5. 返回 `order_id` 时先用 `get_order` 获取状态、金额、币种和分页明细，不能把待支付订单视作
   实例开通成功。取得订单、金额和币种的明确授权后调用 `pay_order`。返回
   `job_id` 时跟踪创建任务，再用 `get_instance` 验证实例状态。测试实例用完后，仅在用户明确授权删除该
   实例时执行删除流程。

### 包周期订单查询、付款与取消

1. 使用 `create_instance` 返回的准确 `order_id` 调用 `get_order`，按 marker 读取后续明细。
   保留金额、币种、度量单位和状态；优惠后金额不包含券、卡抵扣，不自行改写为最终支付金额。
2. 用户选择付款时，展示准确订单号、配置、总额、币种和计费周期。取得明确授权后调用
   `pay_order(order_id, expected_amount="十进制金额", currency="订单币种", confirm=true)`。
   当前工具不主动选券或额外折扣，要求订单原价与优惠后金额均等于授权金额；有差异时交由费用
   中心处理，不能改用较高金额重新付款。该金额校验是提交前检查，不能保证原子扣款上限。
3. 付款提交或响应未知时，核对 `payment_verified` 并继续查询订单，不盲目重试；已处理订单
   不再次付款。托管账号可能自动使用优惠，实际扣款以账单为准。最终用 `get_instance` 确认开通。
4. 用户明确放弃订单后，以 `confirm=true` 调用 `cancel_order`。该工具仅处理未支付的 GaussDB
   订单；服务端复查云端状态和全部明细，拒绝其他产品、混合产品及已付款订单。
5. 核对 `cancellation_verified`，为 false 时继续查询同一订单；已取消订单可返回幂等结果。
   已付款资源需另走退订流程，不能用取消订单或删除按需实例接口代替。
6. 订单工具复用现有 AK/SK/STS，BSS 是全局服务，Endpoint 与数据库区域无关。
   `confirm=true` 不构成人工审批凭据，确认方式由 Agent 客户端实现。

### 购买前选型与询价

1. 收集区域、产品类型、集中式/分布式、部署形态、版本、CPU/内存、存储类型与容量、节点数、
   计费模式、购买时长、是否需要 EIP/备份以及预算上限。缺少关键输入时停在候选方案阶段。
2. 调用 `discover_create_options` 和 `list_flavors` 获取当前区域的实时可售组合，不复用其他区域
   的规格码或价格。
3. 给出三档候选，但必须以实时可售性为准：开发测试优先 `single`，生产高可用优先 `triset`，
   大容量或横向扩展场景比较 `combined` / `hws` 分布式方案。
4. 本 MCP 的 BSS 工具覆盖已有订单查询、付款和待支付订单取消。购买前询价和余额通过独立的 BSS/计费工具调用
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

### 监控诊断

需要解释指标、单位或状态码时，读取
[references/monitoring-metrics.md](references/monitoring-metrics.md)；指标是否可用仍以实时发现为准。

1. 先用 `get_instance` 获取节点和组件；分别查询实例层、逐个 node_id 的节点层，再查询各
   DN/CN component_id 的组件层，并分别分页。仅传 instance_id 不会返回节点/组件指标；
   CES 不展开层级，也不能用 `*` 替代真实 ID。不要固定任何区域、版本或拓扑的指标清单。
2. 将选中的条目连同完整 `dimensions` 传给 `query_monitoring_metrics`；不要省略 CPU 的节点
   维度或会话指标的组件维度。工具会归一维度顺序；时间使用带时区 ISO 8601 或毫秒时间戳。
3. 新建实例可能尚未上报全部指标，缺项时在有界等待后重新发现；不要因缺少某项就创建新资源。
   无数据不等于零或正常。检查 `status`、`observed_window` 和采样数量；曲线截断时摘要仍基于
   本次收到的全部窗口内数据。范围超限时拆批、增大 period 或缩短时间，不自动省略历史窗口。
4. CES 查询复用现有凭证，另需 `ces:metrics:list` 和 `ces:metricData:list` 权限。

### 主备切换与容灾

本 Skill 只用 `get_instance` 查询实例拓扑。需要执行主备切换或容灾变更时，转到华为云
控制台或相应的运维工具操作。

### 删除或其他危险操作

1. 用 `get_instance` 重新读取目标实例，核对 ID、名称、标签、计费方式、备份和保护规则。
2. 展示不可逆影响并取得对该精确资源的明确确认。
3. 调用 `delete_instance(..., confirm=true)`。
4. 跟踪任务并重新查询，直到删除完成或返回可解释的终态。

## 核心命令（MCP 工具）

优先使用以下专用工具：

| 任务 | 工具 | 风险 |
|---|---|---|
| 查询实例 | `list_instances`, `get_instance` | READ |
| 创建选型 | `discover_create_options`, `list_flavors` | READ |
| 创建实例 | `create_instance` | WRITE/计费 |
| 查询包周期订单 | `get_order` | READ |
| 确认付款 | `pay_order` | DANGEROUS/实际扣款 |
| 取消待支付订单 | `cancel_order` | DANGEROUS |
| 规格与容量 | `resize_instance`, `expand_instance` | WRITE/可能中断或计费 |
| 重启 | `restart_instance` | WRITE/中断连接 |
| 参数管理 | `get_instance_parameters`, `update_instance_parameters` | READ/WRITE |
| 备份 | `list_backups`, `create_manual_backup` | READ/WRITE |
| 备份策略 | `get_backup_policy`, `configure_backup_policy` | READ/WRITE |
| 慢 SQL | `analyze_slow_sql`（毫秒时间戳或带时区 ISO 8601） | READ/敏感数据 |
| 异步任务 | `get_job`, `wait_job` | READ |
| 监控 | `list_monitoring_metrics`, `query_monitoring_metrics` | READ |
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
| 计费模式 | 创建/变更必需 | 不推断 | 包周期与订单付款必须明确授权，创建时关闭自动支付 |
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
- 慢 SQL 文本可能包含业务数据，只返回诊断所需字段并遵循最小披露原则。
- 对轮询设置合理停止条件；失败时返回云端错误码、请求 ID 和下一步，不进行无限重试。

## 参考文档

- [MCP 安装与配置](references/mcp-installation-guide.md)：安装、客户端注册、凭证优先级和热加载。
- [IAM 权限策略](references/iam-policies.md)：只读、写入、危险操作及 Project 自动发现权限。
- [MCP 工具参考](references/related-tools.md)：当前场景工具与关键参数。
- [购买前选型与询价](references/purchase-estimation.md)：BSS 路由、三档方案和预算输出。
- [验证方法](references/verification-method.md)：本地与云端验证步骤。
- [验收标准](references/acceptance-criteria.md)：功能、错误处理和安全通过条件。

## 注意事项

- 当前版本不包含 DRS。
- 当前 MCP 只管理 GaussDB（openGauss）控制面；数据面 SQL/DDL 路由到
  `huaweicloud-gaussdb-data`（若已安装），GaussDB(for MySQL) 路由到对应 Skill。
- `logger` 的查询可见不等于公开接口可以创建，禁止静默转换为 `triset`。
- 不在 Skill、示例、日志或回复中保存真实 AK/SK、SecurityToken、数据库密码或完整慢 SQL。
- 删除实例、订单付款和取消订单前，必须核对精确资源并显式确认。

## 安全约束

- 保持环境变量 → MCP 凭证文件 → devkit S1 的优先级；AK/SK/STS Token 来自同一来源，不完整时报错。
- 创建、变更请求的 `is_auto_pay`、`is_auto_renew` 保持 false。获取待支付订单后，按订单、金额、币种取得用户授权，再调用 `pay_order`。`confirm=true` 本身不证明已经获得用户授权。
- `MCP_WRITE_RESULT_UNKNOWN` 或客户端取消不代表云端写入失败；查询已有资源、任务或订单，不自动重提写操作。`MCP_BUSY` 表示容量已满，应稍后重试。
