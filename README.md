# huaweicloud-mcp

> **语言切换：** [English](./README_en.md) | 中文

华为云 MCP Server 共享仓库：为每个华为云服务提供场景化的 MCP 工具，支持本地（stdio）
与远程（streamable-http）部署。

## MCP Server 列表

### 管理与治理

- **[RFS MCP](server/mcp_server_rfs/README.md)**：资源编排服务——HCL 模板一键部署为资源栈、
  执行计划干跑预览、失败部署根因诊断、安全下线。
- **[RC MCP](server/mcp_server_rc/README.md)**：资源中心——全局资源检索与分组管理、资源关系
  查询、ResourceQL 高级查询。

### 数据库

- **[GaussDB MCP](server/mcp_server_gaussdb/README.md)**：GaussDB（openGauss）实例、备份、
  参数、慢 SQL、异步任务，以及按风险分流的完整 OpenAPI 目录。

## 开发者文档

完整开发指南见 [docs/development/](docs/development/README.md)，按功能特性拆为 10 篇：核心包逐模块 API、
工具场景化方法论、service/client 层、护栏、输出错误、三层测试、从零建服务实战、
工程化与发布。参考实现：`server/mcp_server_rfs/`；脚手架：`docs/development/template/`。

## 核心能力（所有服务共享）

- 简化认证：`HUAWEICLOUD_ACCESS_KEY / SECRET_KEY / REGION`，project_id 经 IAM 自动解析
- 安全护栏：风险分级（READ/WRITE/DANGEROUS）、DANGEROUS 二次确认、资源保护名单、
  输出脱敏、结构化审计（默认开启）
- 输出治理：结构化 JSON + token 预算（默认 20 条、字段白名单、超长截断）
- 只读模式：`HUAWEICLOUD_MCP_READ_ONLY=true` 一键拦截全部写操作

## 快速开始

```bash
cd server/mcp_server_rfs
uv sync
export HUAWEICLOUD_ACCESS_KEY=... HUAWEICLOUD_SECRET_KEY=... HUAWEICLOUD_REGION=cn-north-4
uv run mcp_server_rfs
```

## 新服务接入

参见 [docs/08-new-service-walkthrough.md](docs/development/08-new-service-walkthrough.md)：
提 issue → 复制脚手架模板 → 三层开发 → 自测 → 双语 README → PR 审查。

## License

MIT。迁入的 GaussDB 子包保留 [Apache-2.0 许可证](server/mcp_server_gaussdb/LICENSE)。
