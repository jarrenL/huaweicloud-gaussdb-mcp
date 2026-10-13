# 华为云数据库 MCP

[English](README.md)

面向华为云数据库管理场景的开源 MCP Server 工程。当前版本聚焦**云数据库 GaussDB**，不包含 DRS。它把实例、备份、规格、扩容、重启、参数、慢 SQL 和异步任务等管理能力封装为标准 MCP 工具，可接入 AgentArts、OfficeACE、码道 MCP 市场及其他兼容 MCP 的客户端。

当前版本：`0.3.6`；Python `3.10+`；协议传输：stdio、Streamable HTTP；许可证：Apache-2.0。

## 主要能力

- 17 个高频场景工具，覆盖实例创建/删除、规格变更、扩容、重启、备份、参数和慢 SQL。
- 5 个目录式 OpenAPI 工具，动态发现当前 SDK 的 265 个公开请求操作，并按 READ、WRITE、DANGEROUS 分流。
- 实时发现区域、Project、版本、部署形态、规格、可用区、VPC、子网和安全组，不固化区域规格。
- 区分基础版/企业版、集中式/分布式，以及单副本、1 主 2 备、1 主 1 备 1 日志等部署选项。
- 参数修改前实时读取可修改参数及值域；只读、未知和高风险参数受到阻断或二次确认保护。
- 支持 AK/SK、临时安全令牌、项目 ID 自动发现，以及 `0600` 凭证文件热加载。
- 提供只读模式、保护资源名单、规则化确认、递归脱敏和 JSONL 审计。

完整工具表、字段说明和安全行为见 [GaussDB 中文说明](server/mcp_server_gaussdb/README_zh.md)。

## 快速开始

### 从源码运行

```bash
git clone https://github.com/jarrenL/huaweicloud-gaussdb-mcp.git
cd huaweicloud-gaussdb-mcp
uv sync --all-packages --all-groups

export HUAWEICLOUD_ACCESS_KEY="<your-access-key>"
export HUAWEICLOUD_SECRET_KEY="<your-secret-key>"
export HUAWEICLOUD_REGION="cn-north-4"
export HUAWEICLOUD_MCP_READ_ONLY="true"

uv run mcp-server-huaweicloud-gaussdb
```

服务发布到 PyPI 后，也可直接运行：

```bash
uvx mcp-server-huaweicloud-gaussdb
```

### MCP 客户端配置

```json
{
  "mcpServers": {
    "huaweicloud-gaussdb": {
      "command": "uvx",
      "args": ["mcp-server-huaweicloud-gaussdb"],
      "env": {
        "HUAWEICLOUD_ACCESS_KEY": "${HUAWEICLOUD_ACCESS_KEY}",
        "HUAWEICLOUD_SECRET_KEY": "${HUAWEICLOUD_SECRET_KEY}",
        "HUAWEICLOUD_REGION": "cn-north-4",
        "HUAWEICLOUD_MCP_READ_ONLY": "true"
      }
    }
  }
}
```

建议先保持只读模式，调用 `discover_create_options`、`list_instances` 和 `list_openapi_operations` 验证连接。需要执行写操作时，再按运行环境设置护栏和审计，并把 `HUAWEICLOUD_MCP_READ_ONLY` 改为 `false`。

Streamable HTTP 启动命令：

```bash
uv run mcp-server-huaweicloud-gaussdb -t streamable-http
```

默认端点为 `http://<host>:8000/mcp`。对外部署时应在网关配置 HTTPS 和客户端身份认证。可直接参考 [UVX 配置](examples/agentarts-uvx.json) 和 [Streamable HTTP 配置](examples/agentarts-streamable-http.json)。

## 安全使用

1. 为 MCP 使用独立 IAM 用户或临时安全凭证，只授予实际要调用的 GaussDB/VPC/IAM 查询权限。
2. 不要把 AK/SK 写入仓库、客户端共享配置或命令历史；生产环境使用凭证文件热加载或密钥管理系统注入。
3. 首次接入保持 `HUAWEICLOUD_MCP_READ_ONLY=true`。
4. 写操作启用 [安全规则示例](examples/guardrails.example.yaml) 和审计文件；删除、切换、恢复、升级等危险操作必须显式确认。

权限明细以华为云 [GaussDB 权限和授权项](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_188.html) 为准。

## 工程结构

| 路径 | 内容 |
|---|---|
| `libs/huaweicloud_mcp_core` | 公共运行时、凭证、安全护栏、脱敏、审计和统一输出 |
| `server/mcp_server_gaussdb` | GaussDB MCP Server、工具实现、服务层、客户端层和测试 |
| `examples` | AgentArts、凭证热加载和安全规则配置示例 |
| `.github` | 持续集成、Issue 和 Pull Request 模板 |

## 开发和验证

```bash
uv sync --frozen --all-packages --all-groups
uv run --package huaweicloud-mcp-core ruff check libs/huaweicloud_mcp_core/src libs/huaweicloud_mcp_core/tests
uv run --package mcp-server-huaweicloud-gaussdb ruff check server/mcp_server_gaussdb/src server/mcp_server_gaussdb/tests
uv run --package huaweicloud-mcp-core pytest libs/huaweicloud_mcp_core/tests
uv run --package mcp-server-huaweicloud-gaussdb pytest server/mcp_server_gaussdb/tests
uv build --package huaweicloud-mcp-core
uv build --package mcp-server-huaweicloud-gaussdb
```

默认测试使用 Mock，不访问云上资源。只有显式启用 `live` 测试并提供专用测试账号时才可调用华为云；涉及计费资源的测试必须记录创建、任务完成和删除结果。

## 文档

- [GaussDB MCP 完整说明](server/mcp_server_gaussdb/README_zh.md)
- [OpenAPI 云上验证说明](server/mcp_server_gaussdb/OPENAPI_VALIDATION_zh.md)
- [贡献指南](CONTRIBUTING.md)
- [安全策略](SECURITY.md)
- [变更记录](CHANGELOG.md)

## 功能边界

本项目提供**云资源管理**能力，不建立数据库 SQL 会话，不执行任意 SQL，也不提供自然语言转 SQL。当前传输协议是 stdio 和 Streamable HTTP，不提供旧版 SSE 端点。AgentArts、OfficeACE 和码道市场的具体上架状态由各平台发布流程决定；仓库中的配置文件是可复用的接入基线。

## 贡献和支持

提交代码前请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。普通缺陷和功能建议可使用 GitHub Issue 模板；安全问题请按 [SECURITY.md](SECURITY.md) 私下报告，不要公开披露凭证或资源信息。

## 许可证

Apache License 2.0，详见 [LICENSE](LICENSE)。
