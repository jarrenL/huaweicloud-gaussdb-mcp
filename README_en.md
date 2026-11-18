# huaweicloud-mcp

> **Language:** English | [中文](./README.md)

Huawei Cloud MCP Server shared repository: provides MCP tools for each Huawei Cloud service, supporting both local (stdio) and remote (streamable-http) deployment.

## MCP Server List

### Management & Governance

- **[RFS MCP](server/mcp_server_rfs/README_en.md)**: Resource Formation Service — one-click HCL template deployment as stacks, dry-run preview for execution plans, root-cause diagnosis for failed deployments, secure decommissioning.
- **[RC MCP](server/mcp_server_rc/README_en.md)**: Resource Center — global resource search and group management, resource relationship queries, advanced ResourceQL queries.

### Compute

- **[ECS Readonly MCP](server/mcp_server_ecs_readonly)**: Elastic Cloud Server readonly — read-only inventory of instance count / power status / flavor usage / running vCPUs & memory / public & private IPs, for periodic resource auditing scenarios.
- **[ECS Lifecycle MCP](server/mcp_server_ecs_lifecycle)**: Elastic Cloud Server lifecycle — creation (prepaid/postpaid, smart defaults + user_data/EIP slots), modification, deletion, details / listing / async job queries, image / flavor / keypair discovery queries. All mutation tools enforce two-phase confirmation (preview first, `confirm=true` to execute), then re-check protection rules before execution — agents never act on their own.

### Database

- **[GaussDB MCP](server/mcp_server_gaussdb/README_en.md)**: Main capabilities include instance management, backups, parameter management, slow SQL analysis, and monitoring.

## Developer Documentation

The complete development guide is available at [docs/development/](docs/development/README.md), split into 10 feature-focused documents: core package modular API, tool scenario methodology, service/client layers, guardrails, output & errors, three-tier testing, hands-on service creation from scratch, engineering & release. Reference implementation: `server/mcp_server_rfs/`; scaffold: `docs/development/template/`.

## Core Capabilities (Shared Across All Services)

- Simplified authentication: `HUAWEICLOUD_ACCESS_KEY / SECRET_KEY / REGION`, project_id auto-resolved via IAM
- Security guardrails: risk classification (READ/WRITE/DANGEROUS), double confirmation for DANGEROUS operations, resource protection allowlist, output desensitization, structured auditing (enabled by default)
- Output governance: structured JSON + token budget (default 20 items, field allowlist, truncation for oversized content)
- Read-only mode: `HUAWEICLOUD_MCP_READ_ONLY=true` one-click interception of all write operations

## Quick Start

```bash
cd server/mcp_server_rfs
uv sync
export HUAWEICLOUD_ACCESS_KEY=... HUAWEICLOUD_SECRET_KEY=... HUAWEICLOUD_REGION=cn-north-4
uv run mcp-server-rfs
```

## New Service Onboarding

See [docs/08-new-service-walkthrough.md](docs/development/08-new-service-walkthrough.md): open issue → copy scaffold template → three-tier development → self-test → bilingual README → PR review.

## License

MIT
