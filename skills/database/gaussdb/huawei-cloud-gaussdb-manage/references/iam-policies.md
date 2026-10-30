# IAM 权限策略

## 概述

GaussDB 是区域级服务。应在目标区域项目中授权，并按实际启用的 MCP 工具授予最小权限。
角色与策略授权、身份策略授权的授权项名称可能不同，不要把两套模型中的 Action 混写到同一策略。

## 推荐权限分层

| 使用范围 | 推荐系统权限 | 用途 |
|---|---|---|
| 只读接入 | `GaussDB ReadOnlyAccess` | 查询实例和只读 GaussDB 信息 |
| 全功能管理 | `GaussDB FullAccess` | 创建、变更、备份、参数和删除等写操作 |
| 身份策略只读 | `GaussDBReadOnlyPolicy` | 新版身份策略中的只读访问 |
| 身份策略全功能 | `GaussDBFullAccessPolicy` | 新版身份策略中的完整管理 |

生产环境优先创建自定义最小权限策略，不要长期给 MCP 使用管理员或全量权限。

## 场景工具常用授权项

下表采用角色与策略授权中的常用 Action 表达。实际策略应以租户当前采用的授权模型和接口版本为准。

| MCP 能力 | 主要 Action | 依赖或说明 |
|---|---|---|
| 查询实例/详情/任务 | `gaussdb:instance:list` | 实例详情可能需要 VPC/CES 只读权限 |
| 查询创建选项 | `gaussdb:instance:list`, `gaussdb:param:list` | 另需 VPC/子网/安全组查询权限 |
| 创建实例 | `gaussdb:instance:create`, `gaussdb:param:list` | 包周期、KMS 加密另有 BSS/KMS 依赖 |
| 规格变更/节点或磁盘扩容 | `gaussdb:instance:modifySpec` | 可能产生订单或中断 |
| 重启实例 | `gaussdb:instance:restart` | 中断连接 |
| DN 分片主备切换 | `gaussdb:instance:switchShard` | DANGEROUS；切换期间连接可能中断 |
| 删除实例 | `gaussdb:instance:delete` | 包周期退订另需 BSS 权限 |
| 查询/修改参数 | `gaussdb:param:list`, `gaussdb:param:modify` | 修改前必须实时查询可修改元数据 |
| 创建/查询备份 | `gaussdb:backup:create`, `gaussdb:backup:list` | 手工备份创建是写操作 |
| 修改备份策略 | `gaussdb:instance:modifyBackupPolicy` | 先查询当前策略 |
| 查询慢 SQL | `gaussdb:instance:listSlowSql` | SQL 文本包含业务敏感信息 |

创建选型额外需要：

| Action | 用途 |
|---|---|
| `vpc:vpcs:list` | 列出 VPC |
| `vpc:vpcs:get` | 查询 VPC |
| `vpc:subnets:get` | 查询子网 |
| `vpc:securityGroups:get` | 查询安全组 |
| `iam:projects:listProjects` | 缺少 Project ID 时按区域发现项目 |

包周期创建通常还需要 `bss:order:update`、`bss:order:view` 和 `bss:balance:view`；KMS 加密实例
通常需要 `kms:cmk:get`、`kms:cmk:list`。只有请求实际使用这些能力时才授权。

购买前查询账户余额的身份策略授权项是 `billing:balance:view`。BSS 商品询价与客户/伙伴账号
体系相关，使用前按调用主体核对对应 API 的授权要求；不要因为询价失败而给 GaussDB MCP
授予全局管理员权限。

## BSS 订单权限

`get_order` 使用客户 BSS 全局凭证，身份策略授权项为 `billing:order:view`。
`cancel_order` 还需按账号所用授权模型核对订单更新权限，角色/策略授权可能使用
`bss:order:update`；当前取消 API 的身份策略文档未列出额外授权项。参见
[订单详情](https://support.huaweicloud.com/api-oce/api_order_00014.html)和
[取消待支付订单](https://support.huaweicloud.com/api-oce/api_order_00017.html)。
不要因 GaussDB 读写权限正常就假设拥有 BSS 权限；本服务不会自动提权。
`pay_order` 另需身份策略 `billing:order:pay`，角色/策略模式按对应 BSS 支付权限配置。
参见 [支付订单](https://support.huaweicloud.com/api-oce/api_order_00030.html)。
付款是实际扣款操作，测试工具注册或护栏不代表已授权执行真实付款。
默认 BSS 地址为中国站 `https://bss.myhuaweicloud.com`；其他站点需设置
`HUAWEICLOUD_BSS_ENDPOINT`。沿用现有 AK/SK/STS，BSS 不使用数据库区域的 Project ID。

## CES 监控权限

监控工具复用区域项目及凭证，但 GaussDB 的授权不会自动授予 CES 权限：

- `list_monitoring_metrics`：`ces:metrics:list`。
- `query_monitoring_metrics`：`ces:metricData:list`。

按当前授权模型为目标项目单独授予以上查询权限。依据见
[CES 指标发现](https://support.huaweicloud.com/intl/zh-cn/api-ces/ces_03_0023.html)及
[CES 批量查询](https://support.huaweicloud.com/intl/zh-cn/api-ces/ces_03_0034.html)。

## 最小权限策略示例

下面示例覆盖只读发现、实例查询、参数查询、备份查询和慢 SQL。部署前应由账号管理员按当前
授权模型复核 Action：

```json
{
  "Version": "1.1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "gaussdb:instance:list",
        "gaussdb:param:list",
        "gaussdb:backup:list",
        "gaussdb:instance:listSlowSql",
        "vpc:vpcs:list",
        "vpc:vpcs:get",
        "vpc:subnets:get",
        "vpc:securityGroups:get",
        "iam:projects:listProjects"
      ]
    }
  ]
}
```

不要为通用 OpenAPI 目录预先授予所有写权限。先通过 `list_openapi_operations` 和
`describe_openapi_operation` 确定具体 API，再只添加该操作所需 Action。

## 权限失败处理

1. 停止当前操作，不用其他通道绕过权限校验。
2. 记录工具名、区域、云端错误码和请求 ID；删除凭证、密码和 SQL 文本。
3. 根据上表向用户列出缺少的 Action、授权范围和依赖服务。
4. 等待用户确认管理员已完成授权，再重试一次只读验证。
5. 仍失败时检查授权模型、区域项目和企业项目范围，不自动扩大为管理员权限。

✅ 正确：为 `cn-north-4` 的只读诊断授予对应区域的只读策略。

❌ 错误：为了让一个查询成功，直接给长期 AK/SK 绑定全局管理员权限。
