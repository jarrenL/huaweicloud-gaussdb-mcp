# 华为云 GaussDB MCP Server

[English](README_en.md)

## 版本

当前版本：`0.7.0`；Python `3.10+`；MCP Python SDK `2.x`。

## 概述

该服务把华为云 GaussDB 管理 API 封装为 MCP 工具，供 AgentArts、OfficeACE 连接器及其他 MCP 客户端调用。支持 stdio 和 Streamable HTTP，两种模式使用同一套工具、安全护栏和输出协议。当前工程仅支持 GaussDB，不包含 DRS。

## 快速开始

准备 Python 3.10+、`uv` 和具有 GaussDB 查询权限的华为云凭证。若已经通过
`huaweicloud-devkit` 配置凭证，MCP 会自动复用
`~/.config/huaweicloud/credentials.json`。首次接入建议启用只读模式：

```bash
export HUAWEICLOUD_MCP_READ_ONLY="true"
uvx mcp-server-huaweicloud-gaussdb
```

未使用 devkit 时，仍可显式设置 `HUAWEICLOUD_ACCESS_KEY`、
`HUAWEICLOUD_SECRET_KEY` 和 `HUAWEICLOUD_REGION`。

通用 stdio 客户端配置：

```json
{
  "mcpServers": {
    "huaweicloud-gaussdb": {
      "command": "uvx",
      "args": ["mcp-server-huaweicloud-gaussdb"],
      "env": {
        "HUAWEICLOUD_MCP_READ_ONLY": "true"
      }
    }
  }
}
```

先调用 `discover_create_options` 或 `list_instances` 验证区域、权限和 Project 自动发现。完整安装、凭证文件和远程服务配置见后文。

## 分类

数据库 / 云资源管理 / 运维自动化。

## 功能

- 实例创建、查询、规格变更、存储/CN/DN 扩容、重启。
- 自动发现 Project/Domain、引擎版本、规格、可用区、VPC、子网和安全组。
- 创建前显式选择产品类型、集中式/分布式和部署形态；默认推荐基础版单副本用于开发联调。
- 手工备份、备份查询、自动备份策略查询与修改。
- 参数查询和修改、支持毫秒时间戳或带时区 ISO 8601 的慢 SQL 分析，以及有界异步任务等待。
- AK/SK/临时安全令牌、devkit S1 凭证复用、项目 ID 自动发现、凭证文件热加载。
- 只读模式、规则化阻断/确认/告警、敏感信息脱敏和 JSONL 审计。
- 统一分页、字段白名单、长字段截断和可供模型理解的错误结构。

- 通过 CES 实时发现和批量查询实例、节点及组件监控指标。
- 通过 BSS SDK 查询 GaussDB 包周期订单金额、状态和明细，确认后取消待支付订单。
- 核对订单金额和币种后，通过 BSS SDK 确认余额支付，并复查付款状态。

## 可用工具

| 工具 | 场景 | 风险 | API 文档 |
|---|---|---|---|
| `list_instances` | 分页查询实例 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_328.html) |
| `get_instance` | 查询单实例及拓扑、网络、存储信息 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_328.html) |
| `list_flavors` | 创建或变更前查询可用规格 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_084.html) |
| `discover_create_options` | 自动发现创建实例所需的全部云端参数并给出推荐配置 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `create_instance` | 创建 GaussDB 实例 | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_017.html) |
| `get_order` | 查询 GaussDB 订单状态、金额和分页明细 | READ | [BSS API](https://support.huaweicloud.com/api-oce/api_order_00014.html) |
| `pay_order` | 核对准确金额、币种并确认支付 GaussDB 订单 | DANGEROUS | [BSS API](https://support.huaweicloud.com/api-oce/api_order_00030.html) |
| `cancel_order` | 取消待支付 GaussDB 订单；确认、保护检查并复查状态 | DANGEROUS | [BSS API](https://support.huaweicloud.com/api-oce/api_order_00017.html) |
| `delete_instance` | 永久删除实例；强制确认并二次检查云端保护属性 | DANGEROUS | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `resize_instance` | 变更 CPU/内存规格 | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `expand_instance` | 扩容存储、CN 或 DN 分片 | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_019.html) |
| `restart_instance` | 在维护窗口重启实例 | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_025.html) |
| `get_instance_parameters` | 查询参数、范围和重启要求 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `update_instance_parameters` | 修改最多 100 个参数 | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `list_backups` | 查询实例备份 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_162.html) |
| `create_manual_backup` | 创建手工备份 | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `get_backup_policy` | 查询自动备份策略 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `configure_backup_policy` | 修改自动备份策略 | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `analyze_slow_sql` | 按平均执行时间分析慢 SQL，时间支持毫秒时间戳或带时区 ISO 8601 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_297.html) |
| `get_job`, `wait_job` | 单次查询任务，或在超时范围内轮询到终态 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `list_monitoring_metrics` | 实时发现监控指标及完整维度 | READ | [CES API](https://support.huaweicloud.com/api-ces/ces_03_0023.html) |
| `query_monitoring_metrics` | 批量查询监控曲线及摘要 | READ | [CES API](https://support.huaweicloud.com/api-ces/ces_03_0034.html) |
| `list_openapi_operations` | 分页检索当前 SDK 的全部公开 GaussDB OpenAPI | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `describe_openapi_operation` | 查询指定接口的完整嵌套请求结构 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `invoke_read_openapi` | 调用目录中归类为只读的接口 | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `invoke_write_openapi` | 调用目录中归类为可逆或新增型写接口 | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `invoke_dangerous_openapi` | 调用删除、停机、切换、恢复、升级和计费敏感接口 | DANGEROUS | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |


### 包周期订单

`create_instance` 的 `configuration.charge_info` 支持包年/包月，例如：

```json
{
  "charge_mode": "prePaid",
  "period_type": "month",
  "period_num": 1,
  "is_auto_pay": false,
  "is_auto_renew": false
}
```

包月可选 1-9 个月，包年可选 1-3 年。先取得用户对计费配置和费用的授权。
创建返回 `order_id` 时，用 `get_order(order_id=...)` 查询金额、币种、状态和明细；
明细默认 20 条，使用返回的 marker 分页。`amount_after_discount` 为优惠后、不含券和卡的
金额；金额需结合返回币种和度量单位解释。待支付订单不表示实例已经开通；返回 `job_id`
时才使用 `wait_job` 跟踪任务，并在开通后通过 `get_instance` 验证实例状态。

取消前先查询并确认准确订单，再调用 `cancel_order(order_id=..., confirm=true)`。
服务重新检查云端待支付状态、支付时间、保护规则及全部明细，拒绝已支付、其他产品或混合产品
订单；单次取消最多核验 1000 条明细。已取消订单返回幂等结果。取消后检查
`cancellation_verified`；为 false 时继续用 `get_order` 查询，不盲目重复提交。

订单工具复用 AK/SK、STS 和凭证热加载，使用全局 BSS SDK 凭证。中国站 BSS Endpoint 默认
为 `https://bss.myhuaweicloud.com`，不随数据库区域拼接；其他站点通过
`HUAWEICLOUD_BSS_ENDPOINT` 指定对应 BSS 地址。订单查询需 `billing:order:view`；取消需按
账号所用授权模型核对 [BSS 权限说明](https://support.huaweicloud.com/api-oce/api_order_00017.html)
（角色/策略授权可能涉及 `bss:order:update`）。只读模式拦截取消，危险操作需要确认并写入审计。

付款前先用 `get_order` 核对准确订单并取得用户对金额和币种的授权，然后调用：

```json
{
  "order_id": "<订单号>",
  "expected_amount": "1248.00",
  "currency": "CNY",
  "confirm": true
}
```

上述对象是 `pay_order` 的调用参数，金额和币种应采用当前订单的实际值，金额使用十进制字符串。
服务核验全部明细并在付款前刷新状态、金额与保护属性，仅提交一次付款请求，不自动重试；
已取消、非待支付或混合产品订单被拒绝，处理中/已完成订单直接返回当前状态。
付款需要 `billing:order:pay` 及订单读取权限，使用账号余额（现金或信用账户由云端规则决定）。

当前工具不主动选择优惠券或额外折扣，要求 `official_amount` 与 `amount_after_discount`
同时等于确认金额；两者不同会拒绝付款，避免丢失优惠。需要券/折扣的订单请在费用中心完成。
托管账户可能由云端自动使用优惠，最终现金扣款以账单为准。`expected_amount` 是提交前核对值，
BSS 付款接口不接收该字段，因此它不构成原子扣款上限。

付款返回 `payment_submitted` 与 `payment_verified`。超时等异常可能使提交结果未知
（`payment_submitted=null`），此时先查询同一订单，不自动再次付款。复查发现订单金额与授权
不同会返回告警。当前进程串行处理付款请求；跨进程和重启后的状态以 BSS 为准。
付款受理不等于实例开通；继续查询 `get_order`，再用 `get_instance` 确认实例状态。

退款、资源退订及购买前询价需使用独立的计费能力。`confirm=true` 是调用参数，
不等于服务端核验过人工审批；具体确认界面由 Agent 客户端实现。

### CES 监控

1. 先用 `get_instance` 获取节点和组件。仅传 `instance_id` 查询实例层指标；逐个增加实际
   `node_id` 查询 CPU/内存等节点指标，再增加 DN/CN 的 `component_id` 查询组件指标。
   每层分别按 marker 分页；CES 不会自动展开下层，也不能用 `*` 代替真实 ID。
2. 将选中条目连同完整 `dimensions` 传给 `query_monitoring_metrics`。实例、节点和组件指标
   分别需要相应层级的维度；工具会将 CES 返回的无序维度归一为实例、节点、组件顺序。
3. 时间支持毫秒时间戳或带时区 ISO 8601；支持聚合粒度和 average/min/max/sum/variance。
   单次最多 20 条序列，默认每条显示最近 20 个点；摘要覆盖本次取得的所有窗口内数据。
   超过 CES 3000 点预算时要求缩短时间、增大粒度或拆批，避免云端静默缩短查询窗口。

沿用现有 AK/SK、STS、region 和 Project ID；另外需要 `ces:metrics:list` 与
`ces:metricData:list` 权限。没有采样时返回 `no_data`，不将其视作零值或运行正常。
具体维度和采集限制见 [GaussDB 监控指标](https://support.huaweicloud.com/intl/zh-cn/usermanual-gaussdb/gaussdb_01_238.html)。

各项指标的中文含义、单位、三层维度和读数注意点见
[监控指标参考](../../skills/database/gaussdb/huawei-cloud-gaussdb-manage/references/monitoring-metrics.md)。
该文档整理了实测的 58 项指标，当前实例的可用项仍以实时发现为准。

### 全量 OpenAPI 访问

服务启动时会从已安装的华为云 GaussDB SDK 自动发现公开请求接口。`0.7.0` 基于 SDK `3.1.218` 可发现 265 个请求型操作，包括版本化和历史兼容接口。为避免把数百个工具结构同时放入模型上下文，调用流程为：

1. 使用 `list_openapi_operations` 按名称、能力分类或风险分页检索。
2. 使用 `describe_openapi_operation` 获取字段名、嵌套对象、数组及 SDK 模型信息。
3. 按目录给出的风险等级调用对应的 `invoke_*_openapi` 工具；风险通道不匹配时服务会拒绝调用。

`DANGEROUS` 通道始终要求 `confirm=true`。请求包含 `instance_id` 时，服务还会重新读取云端实例并校验保护 ID、名称和标签。SDK 升级后新增接口会自动进入目录，但发布前仍需复核其风险分类和云端约束。

`attach_eip` 只负责绑定或解绑已有公网 IP。如果没有可用 EIP，先通过华为云 VPC/EIP 的
`CreatePublicip`（例如 `hcloud EIP CreatePublicip`）创建，再把公网地址和公网 IP ID 传给
`attach_eip`，最后用 `list_binded_eips` 验证。

长任务优先调用 `wait_job`，避免 Agent 多轮发起 `get_job`。`SWITCHDN` 任务成功后，实例可能
因自动备份短暂处于 `BACKING UP`；开始下一项写操作前，应持续调用 `get_instance` 直到状态为
`ACTIVE`。

### 创建选型

先调用 `discover_create_options`。它会在工具参数模型中直接提供以下枚举，并结合当前区域实时查询部署模板、磁盘类型、可售规格与可用区，再生成 `recommended_configuration`：

- `product_type`：`basic`（基础版，默认）、`enterprise`（企业版）或 `ecology`（生态版；仍需有匹配的实时规格）。
- `deployment_mode`：集中式使用 `single`（单副本，默认）、`triset`（1 主 2 备）或 `logger`（1 主 1 备 1 日志）；基础版分布式使用 `combined`（混合部署），企业版/生态版分布式使用 `hws`（独立部署）。省略时由 `ha_mode + product_type` 自动推导。
- `ha_mode`：`centralization_standard`（集中式，默认）或 `enterprise`（分布式创建模式）。基础版分布式的规格查询会自动映射到 `combined` 规格族。

默认组合是 `basic + centralization_standard + single`，请求体中使用 `ha.instance_mode=basic`、`replica_num=1` 和一个可用区条目。单副本不提供高可用或 SLA，只适合开发和功能测试。生产环境应显式选择 `triset` 或经过评审的 `logger`。

返回的 `create_field_options` 还列出一致性、复制模式、磁盘类型与容量规则、按需/包周期计费、同/跨可用区、端口、时区、备份窗口、备份保留期、分片数、协调节点数和开关类字段；`create_parameter_groups` 将它们进一步拆成公共参数、集中式专属参数和分布式专属参数。

部署模板、规格、磁盘类型和可用区均按当前凭证所在区域及所选引擎版本实时查询。代码中不保存某个区域的规格数量或规格码；`available_flavor_count`、`available` 和 `flavors_truncated` 说明本次实时查询结果。基础版分布式查询 `combined` 规格族，企业版分布式查询 `enterprise` 规格族。调用时会遍历规格查询的全部分页用于可用性判断，再按 `limit` 截取返回，避免不同区域的数量或排序导致误判。分布式返回 `availability_semantics=catalog_candidate` 时表示目录中存在候选，创建时仍由云端最终校验区域、租户、内核和产品版绑定关系。

当前公开 v3.2 创建请求没有 `solution` 字段。`single` 和 `triset` 可由公开字段唯一表达；`logger` 虽可通过部署模板查询确认，但专用 `create_instance` 会标记 `direct_create_supported=false` 并拒绝把它静默转换成 `triset`。需要直接创建 `logger` 时，应先与 GaussDB 接口人确认控制台使用的公开创建映射。

### 参数修改安全

`update_instance_parameters` 不接受盲写。每次修改前都会调用当前推荐的 v3.2 实例参数查询接口，并按实例当前版本返回的元数据逐项检查：

- 参数名必须存在，且云端明确返回 `readonly=false`；返回 `true` 时标记为 `read_only`，缺失时标记为 `unknown` 并失败关闭。
- 返回旧值、新值、类型、`value_range`、是否需要重启和风险原因；清晰的布尔、整数、浮点、枚举和数值区间会先在本地校验，云端继续执行最终值域校验。
- 值没有变化时不发写请求。
- 需要重启，或属于耐久性、安全、复制、审计、内存和连接上限等敏感参数时，第一次只返回预览，必须再次传 `confirm=true` 才会提交。
- `get_instance_parameters(modifiable_only=true)` 可只查看当前实例允许直接修改的参数，同时会返回风险等级。
- `update_instance_configuration` 不能通过通用 OpenAPI 写通道绕过上述检查，必须使用场景工具。


### 备份策略和标签接口细节

- `period` 表示星期，格式如 `1,3,5`；`differential_period` 表示差量备份间隔分钟数，只接受 `15`、`30`、`60`、`180`、`360`、`720`、`1440`。
- 查询接口把 `differential_period` 返回为整数，写入 SDK 模型声明为字符串。服务会把查询结果统一为整数，并在写入时自动转换，因此可以把读取值直接传回配置工具。
- 云端历史字段 `differential_priod` 会被归一为 `differential_period`，不会暴露两个含义重复的字段。
- 省略 `differential_period` 时，服务会读取当前策略并自动保留该值，以兼容更新时强制要求该字段的分布式实例。
- 标签接口请求形态不一致：`add_instance_tags` 使用 `request.body.tags` 数组，`delete_instance_tag` 使用与 `instance_id` 平级的顶层 `key`，不接受 `body`。OpenAPI 列表和描述结果会直接返回两者的请求示例。

接口能力以华为云 [GaussDB API 概览](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) 为准；规格查询见[查询数据库规格](https://support.huaweicloud.com/intl/zh-cn/api-gaussdb/gaussdb_api_084.html)，实例查询见[查询数据库实例列表](https://support.huaweicloud.com/intl/zh-cn/api-gaussdb/gaussdb_api_328.html)，实例创建见[创建数据库实例](https://support.huaweicloud.com/intl/zh-cn/api-gaussdb/gaussdb_api_017.html)，扩容见[扩容实例](https://support.huaweicloud.com/intl/zh-cn/api-gaussdb/gaussdb_api_019.html)，重启见[重启数据库实例](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_025.html)，备份查询见[查询备份列表](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_162.html)，慢 SQL 见[查询慢 SQL](https://support.huaweicloud.com/intl/zh-cn/api-gaussdb/gaussdb_api_297.html)。

## 使用指南

### 前置条件

1. 准备具有所需 GaussDB 最小权限的 IAM 用户；授权项可参考[权限和授权项](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_188.html)。
2. 安装 Python 3.10+；使用 UVX 时安装 [uv](https://docs.astral.sh/uv/)。
3. 准备区域名，例如 `cn-north-4`，以及 AK/SK。生产环境建议使用临时安全凭证。

### 安装

发布到 PyPI 后可一键运行：

```bash
uvx mcp-server-huaweicloud-gaussdb
```

也可安装后运行：

```bash
pip install mcp-server-huaweicloud-gaussdb
mcp-server-huaweicloud-gaussdb
```

从开源仓开发版运行：

```bash
uvx --from "git+https://github.com/huaweicloud/huaweicloud-mcp.git#subdirectory=server/mcp_server_gaussdb" mcp-server-huaweicloud-gaussdb
```

上面的 Git UVX 方式要求公共核心包已先发布到 PyPI。需要修改源码时使用工作区方式：

```bash
git clone https://github.com/huaweicloud/huaweicloud-mcp.git
cd huaweicloud-mcp/server/mcp_server_gaussdb
uv sync --frozen
uv run mcp_server_gaussdb
```

Python 服务使用 UVX/PIP 发布链路，不额外维护功能重复的 NPX 包。

`mcp_server_gaussdb` 是本仓库标准入口；保留 `mcp-server-huaweicloud-gaussdb` 作为兼容入口，
两个命令启动同一个 Server。为兼容已有 PyPI/UVX 配置，分发包名仍为
`mcp-server-huaweicloud-gaussdb`，不是新增第二个服务包。

源码工作区的客户端配置（在官方仓库合入前也可指向本分支下载目录）：

```json
{
  "mcpServers": {
    "huaweicloud-gaussdb": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/huaweicloud-mcp/server/mcp_server_gaussdb", "mcp_server_gaussdb"],
      "env": {"HUAWEICLOUD_MCP_READ_ONLY": "true"}
    }
  }
}
```

## 配置

### 环境变量

| 变量 | 必需 | 说明 |
|---|---:|---|
| `HUAWEICLOUD_ACCESS_KEY` | 是* | IAM Access Key；优先级最高 |
| `HUAWEICLOUD_SECRET_KEY` | 是* | IAM Secret Key；优先级最高 |
| `HUAWEICLOUD_REGION` | 是* | 区域，例如 `cn-north-4`；优先级最高 |
| `HUAWEICLOUD_PROJECT_ID` | 否 | 项目 ID；缺省时通过 IAM 按区域发现 |
| `HUAWEICLOUD_DOMAIN_ID` | 否 | 使用全局凭证时的账号 ID |
| `HUAWEICLOUD_SECURITY_TOKEN` | 否 | 临时安全令牌 |
| `HUAWEICLOUD_ENDPOINT` | 否 | 自定义 GaussDB Endpoint |
| `HUAWEICLOUD_CES_ENDPOINT` | 否 | 可选的 CES Endpoint；默认由当前区域的 CES SDK 解析 |
| `HUAWEICLOUD_BSS_ENDPOINT` | 否 | BSS Endpoint；默认 `https://bss.myhuaweicloud.com`，其他站点显式指定 |
| `HUAWEICLOUD_IAM_ENDPOINT` | 否 | 项目 ID 自动发现使用的 IAM Endpoint，默认 `https://iam.myhuaweicloud.com` |
| `HUAWEICLOUD_MCP_CREDENTIALS_FILE` | 否 | MCP 自管热加载凭证 JSON；权限必须为 `0600` |
| `HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE` | 否 | devkit S1 路径；默认 `~/.config/huaweicloud/credentials.json` |
| `HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS` | 否 | `1`/`true` 时关闭 devkit S1 自动复用 |
| `HUAWEICLOUD_MCP_READ_ONLY` | 否 | `true` 时阻断全部 WRITE/DANGEROUS 工具 |
| `HUAWEICLOUD_MCP_GUARDRAILS_CONFIG` | 否 | YAML 安全规则文件路径 |
| `HUAWEICLOUD_MCP_PROTECTED_IDS` | 否 | 逗号分隔的保护资源 ID |
| `HUAWEICLOUD_MCP_PROTECTED_NAMES` | 否 | 逗号分隔的保护资源名称 |
| `HUAWEICLOUD_MCP_PROTECTED_TAGS` | 否 | 逗号分隔的保护标签，如 `environment=production` |
| `HUAWEICLOUD_MCP_AUDIT_FILE` | 否 | JSONL 审计文件路径；审计始终写入 stderr |
| `MCP_SERVER_HOST` | 否 | HTTP 监听地址，默认 `0.0.0.0` |
| `MCP_SERVER_PORT` | 否 | HTTP 端口，默认 `8000` |

`*` 可由显式环境变量、MCP 凭证文件或 devkit S1 提供。读取优先级按字段为：环境变量、
MCP 凭证文件、devkit S1。`project_id` 和 `domain_id` 不从 devkit 读取；未显式设置
`project_id` 时继续通过 IAM 按区域自动发现。

### 复用 huaweicloud-devkit 凭证

devkit 的 S1 文件使用 `ak`、`sk`、`securityToken`、`region` 字段。MCP 会分别映射为
`access_key`、`secret_key`、`security_token`、`region`。该文件由 devkit 管理，因此读取时
不强制 `0600`，但仍要求它是有效的普通 JSON 对象。每次工具调用都会重新读取，执行
`auth_switch persist` 后无需在 MCP 客户端重复配置 AK/SK。

在 opencode 等本地客户端中只需保留运行策略：

```json
{
  "environment": {
    "HUAWEICLOUD_MCP_READ_ONLY": "true"
  }
}
```

### 凭证热加载

复制 `examples/credentials.example.json`，设置权限并通过环境变量指定：

```bash
cp examples/credentials.example.json credentials.json
chmod 600 credentials.json
export HUAWEICLOUD_MCP_CREDENTIALS_FILE="$PWD/credentials.json"
```

每次工具调用都会重新读取文件，无需重启进程。轮换时应先写入同目录临时文件、设置 `0600`，再原子替换正式文件；格式错误或权限过宽会失败关闭，写操作不会使用旧凭证继续执行。

### 安全护栏

参考 `examples/guardrails.example.yaml`。规则可按工具名、风险级别、资源 ID/前缀、名称正则和标签执行 `block`、`confirm` 或 `warn`。所有写工具均接受 `confirm` 参数，命中确认规则时先返回 `confirmation_required`，复核后以 `confirm=true` 再调用。

保护规则在工具入口检查参数。`delete_instance` 还会在删除前重新读取云端实例，并按实际 ID、名称和标签执行第二次保护检查。所有 `DANGEROUS` 工具即使没有命中自定义规则，也必须以 `confirm=true` 调用。

## 使用 UVX 运行

AgentArts 的 UVX 配置示例：

```json
{
  "mcpServers": {
    "huaweicloud-gaussdb": {
      "command": "uvx",
      "args": ["mcp-server-huaweicloud-gaussdb"],
      "env": {
        "HUAWEICLOUD_MCP_READ_ONLY": "true"
      }
    }
  }
}
```

AgentArts 支持 UVX stdio 和 Streamable HTTP；平台说明见[自定义接入 MCP](https://support.huaweicloud.com/usermanual-agentarts0/agentarts_05_0136.html)。远程模式启动命令：

```bash
mcp-server-huaweicloud-gaussdb -t streamable-http
```

默认 MCP 地址为 `http://<host>:8000/mcp`。远程服务需要可被 AgentArts 访问，生产部署应在前置网关配置 HTTPS 和客户端鉴权。仓库中的 `examples/agentarts-*.json` 可作为码道 MCP 市场、AgentArts 和 OfficeACE 连接器上架配置的基线。

## 示例

安全的规格变更流程：

1. 调用 `get_instance` 核对实例状态和 ID。
2. 调用 `list_flavors` 选择 `spec_code`。
3. 调用 `create_manual_backup`，再用 `list_backups` 确认备份可用。
4. 调用 `resize_instance`；若策略要求确认，复核影响后使用 `confirm=true`。
5. 使用返回的 `job_id` 调用 `get_job`，直到任务到达终态。

所有写接口都可能异步执行。MCP 调用成功只表示云 API 已受理，不表示资源变更已经完成。

## 客户端兼容性

| 客户端或平台 | 接入方式 | 说明 |
|---|---|---|
| AgentArts | UVX stdio / Streamable HTTP | 可使用仓库 `examples/agentarts-*.json` 作为配置基线 |
| OfficeACE、码道 MCP 市场 | 平台支持的 stdio / Streamable HTTP | 上架字段和发布状态以平台流程为准 |
| Claude Desktop 等桌面客户端 | stdio | 客户端需支持 `command`、`args` 和 `env` 配置 |
| 其他标准 MCP 客户端 | stdio / Streamable HTTP | 远程端点为 `/mcp` |

本服务不提供旧版 SSE 传输。它管理 GaussDB 云资源，不建立数据库 SQL 会话，不执行任意 SQL，也不提供自然语言转 SQL。

## 权限建议

- 只读发现：授予所用 GaussDB 查询 API，以及创建选型所需的 VPC、子网和安全组查询权限。
- 写操作：只增加实际启用工具对应的创建、备份、变更、扩容、重启或参数修改权限。
- 危险操作：删除、切换、恢复、升级及计费敏感接口建议使用单独身份或临时授权，并配合 MCP 的确认规则。
- Project 自动发现：需要 IAM 项目查询权限；如果显式提供 `HUAWEICLOUD_PROJECT_ID`，服务无需为此推断其他 Project。

每个接口的授权项以华为云[权限和授权项](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_188.html)为准。不要为方便而把长期管理员凭证配置到 MCP 客户端。

## 开发、测试和发布

```bash
# From the repository root:
bash scripts/test.sh gaussdb
uv build --directory libs/huaweicloud_mcp_core
uv build --directory server/mcp_server_gaussdb
```

默认测试不访问云上资源。Live 验证只能在专用测试账号中显式启用；创建计费资源时必须在失败路径也执行清理，并确认删除任务到达终态。发布前还应检查 wheel 元数据、全新 Python 3.10 环境安装、MCP 工具列表，以及交付包中是否存在凭证和资源标识。

## 贡献和支持

贡献流程、安全报告方式和版本变更分别见仓库根目录的 `CONTRIBUTING.md`、`SECURITY.md` 和 `CHANGELOG.md`。普通问题可使用 GitHub Issue 模板；凭证泄露和安全问题不得提交到公开 Issue。

## 许可证

Apache License 2.0。
