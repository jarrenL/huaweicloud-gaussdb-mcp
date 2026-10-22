# huaweicloud-mcp 开发者文档

## 文档索引

| 篇 | 主题 |
|---|---|
| [00-overview.md](00-overview.md) | 总览与导读、读者画像、阅读路径 |
| [01-architecture.md](01-architecture.md) | 总体架构、MCP 是什么、仓库布局、三层架构、命名规范 |
| [02-core.md](02-core.md) | 公共核心包逐模块 API 级讲解（config/credentials/errors/security/guardrails×5/output/server） |
| [03-tools.md](03-tools.md) | 工具层：场景化方法论、命名动词表、docstring、@guard、confirm 协议 |
| [04-service-client.md](04-service-client.md) | service 编排 + client SDK 封装、asyncio.to_thread、字段白名单、轮询范式 |
| [05-guardrails.md](05-guardrails.md) | 安全护栏五件套：分级/保护名单双防线/脱敏/审计/fail-closed |
| [06-output-errors.md](06-output-errors.md) | 输出信封（page_result/single_result）、token 预算、错误 JSON、异常转换链 |
| [07-testing.md](07-testing.md) | 三层单元测试：注入策略 + RFS/VPC 真实测试代码 |
| [08-new-service-walkthrough.md](08-new-service-walkthrough.md) | 从零建 VPC 服务全流程（template 拷贝→client→service→tools→tests→README→PR）+ 踩坑实录 |
| [09-engineering-release.md](09-engineering-release.md) | uv/ruff/mypy/pytest、CI、版本、双渠道发布、文档规范、当前缺口坦白 |

## 参考实现（可运行、全绿）

| 服务 | 位置 | 验证状态 | 说明 |
|---|---|---|---|
| RFS | [`server/mcp_server_rfs/`](../../server/mcp_server_rfs) | 完整三层测试 | 最早的参考实现，6 工具 |
| VPC | [`server/mcp_server_vpc/`](../../server/mcp_server_vpc) | ruff✓ / mypy strict✓ / 26 测试✓ / 覆盖率 92% | 实战篇产物，4 工具覆盖三级风险 + 护栏双防线 |

## 脚手架

- [`template/`](template) — 可运行最小骨架，`PLACEHOLDER` 待替换。新服务从 `cp -r docs/development/template server/mcp_server_<service>` 起步。

## 新服务开发者最小路径

1. 读 [00-overview.md](00-overview.md) → [01-architecture.md](01-architecture.md) → [02-core.md](02-core.md)
2. 跟 [08-new-service-walkthrough.md](08-new-service-walkthrough.md) 动手跑 VPC（或 `cp -r docs/development/template` 建自己的）
3. 回查 [03-tools.md](03-tools.md) / [04-service-client.md](04-service-client.md) / [05-guardrails.md](05-guardrails.md) / [07-testing.md](07-testing.md)
4. 自测全绿（[09-engineering-release.md §9.9](09-engineering-release.md)）→ PR（审查清单见 §9.5）

## 旧文档迁移说明

本目录各篇按功能特性拆分自历史单文件规范；原始内容备份为仓库根的 `DEVELOPMENT_SPEC2.md`。旧锚点链接（如 `#7-安全护栏`）请改用本目录相对链接（如 [05-guardrails.md](05-guardrails.md)）。

## GaussDB 接入

- [公共核心包 1.2 兼容说明](core-1.2-migration.md)
