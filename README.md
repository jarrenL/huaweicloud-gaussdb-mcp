# Huawei Cloud Database MCP

[中文说明](README_zh.md)

Open-source MCP servers for Huawei Cloud database management. The current release focuses on **GaussDB** and excludes DRS. It exposes instance, backup, resize, expansion, restart, parameter, slow-SQL, and asynchronous-job management through standard MCP tools for AgentArts, OfficeACE, CodeArts MCP Marketplace, and other MCP-compatible clients.

Current version: `0.4.0`; Python `3.10+`; transports: stdio and Streamable HTTP; license: Apache-2.0.

## Highlights

- 18 task-oriented tools for common GaussDB lifecycle and operations workflows, including bounded
  asynchronous-job waiting and ISO 8601 slow-SQL windows.
- 5 catalog tools that dynamically expose 265 public SDK request operations through READ, WRITE, and DANGEROUS lanes.
- Live discovery of project, region, engine version, deployment form, flavor, AZ, VPC, subnet, and security group.
- Explicit product-edition, centralized/distributed, and deployment-form selection without hard-coded regional flavors.
- Live parameter metadata checks, value-range validation, and confirmation for sensitive or restart-requiring changes.
- Reuse of huaweicloud-devkit S1 credentials, AK/SK, temporary tokens, project discovery, and hot-reloaded mode-`0600` credential files.
- Read-only mode, protected resources, policy-based confirmation, recursive masking, and JSONL auditing.
- Clear EIP service boundaries: GaussDB binds existing EIPs, while allocation is performed through
  Huawei Cloud VPC/EIP.

See the [GaussDB server guide](server/mcp_server_gaussdb/README.md) for the complete tool and configuration reference.

## Quick start

When `huaweicloud-devkit` is configured, the server automatically reads
`~/.config/huaweicloud/credentials.json`, so the MCP client does not need another AK/SK copy.
Environment variables and the MCP-managed credential file remain available without devkit.

Run from source:

```bash
git clone https://github.com/jarrenL/huaweicloud-gaussdb-mcp.git
cd huaweicloud-gaussdb-mcp
uv sync --all-packages --all-groups

export HUAWEICLOUD_MCP_READ_ONLY="true"

uv run mcp-server-huaweicloud-gaussdb
```

After PyPI publication, run it directly with:

```bash
uvx mcp-server-huaweicloud-gaussdb
```

Generic stdio client configuration:

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

Keep read-only mode enabled for the first connection and validate it with `discover_create_options`, `list_instances`, and `list_openapi_operations`. Configure guardrails and audit output before enabling writes.

Start Streamable HTTP with:

```bash
uv run mcp-server-huaweicloud-gaussdb -t streamable-http
```

The default endpoint is `http://<host>:8000/mcp`. Public deployments should use HTTPS and client authentication at the gateway. See the ready-to-adapt [UVX](examples/agentarts-uvx.json) and [Streamable HTTP](examples/agentarts-streamable-http.json) examples.

## Security basics

Use a dedicated least-privilege IAM principal or temporary security credentials. Never commit AK/SK values. Begin in read-only mode, then configure [guardrails](examples/guardrails.example.yaml) and audit output before enabling writes. Destructive, disruptive, restore, upgrade, and billing-sensitive operations always require explicit confirmation.

See the official [GaussDB permissions reference](https://support.huaweicloud.com/intl/en-us/api-gaussdb/gaussdb_api_188.html).

## Repository layout

| Path | Contents |
|---|---|
| `libs/huaweicloud_mcp_core` | Shared runtime, credentials, guardrails, masking, auditing, and output contracts |
| `server/mcp_server_gaussdb` | GaussDB server, tools, service/client layers, and tests |
| `skills/database/gaussdb/huawei-cloud-gaussdb-manage` | Agent Skill for safe GaussDB management through this MCP server |
| `examples` | AgentArts, credential hot-reload, and guardrail examples |
| `.github` | Continuous integration, issue templates, and pull request template |

## Development

```bash
uv sync --frozen --all-packages --all-groups
uv run --package huaweicloud-mcp-core ruff check libs/huaweicloud_mcp_core/src libs/huaweicloud_mcp_core/tests
uv run --package mcp-server-huaweicloud-gaussdb ruff check server/mcp_server_gaussdb/src server/mcp_server_gaussdb/tests
uv run --package huaweicloud-mcp-core pytest libs/huaweicloud_mcp_core/tests
uv run --package mcp-server-huaweicloud-gaussdb pytest server/mcp_server_gaussdb/tests
uv build --package huaweicloud-mcp-core
uv build --package mcp-server-huaweicloud-gaussdb
```

The default test suite uses mocks and does not access cloud resources. Live tests must be explicitly enabled with a dedicated test account; tests that create billable resources must capture creation, terminal-job, and cleanup evidence.

## Documentation

- [GaussDB MCP server guide](server/mcp_server_gaussdb/README.md)
- [GaussDB management Skill](skills/database/gaussdb/huawei-cloud-gaussdb-manage/SKILL.md)
- [OpenAPI live-validation notes (Chinese)](server/mcp_server_gaussdb/OPENAPI_VALIDATION_zh.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Changelog](CHANGELOG.md)

## Scope

This project manages cloud resources. It does not open database SQL sessions, execute arbitrary SQL, or provide natural-language-to-SQL features. It supports stdio and Streamable HTTP, not the legacy SSE transport. Marketplace publication is handled by each platform; the repository examples are reusable onboarding baselines.

## Contributing and support

Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a change. Use GitHub issue templates for regular bugs and feature requests. Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md), without disclosing credentials or resource details in public issues.

## License

Apache License 2.0. See [LICENSE](LICENSE).
