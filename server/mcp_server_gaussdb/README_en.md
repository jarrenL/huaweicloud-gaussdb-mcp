# Huawei Cloud GaussDB MCP Server

[中文说明](README.md)

## Version

Current version: `0.5.1`; Python `3.10+`; MCP Python SDK `2.x`.

## Overview

This MCP server exposes Huawei Cloud GaussDB management APIs to AgentArts, OfficeACE connectors, and other MCP clients. It supports stdio and Streamable HTTP. The current scope is GaussDB only; DRS is excluded.

## Quick start

Prepare Python 3.10+, `uv`, and a Huawei Cloud credential with GaussDB read permissions. If
`huaweicloud-devkit` is configured, the MCP automatically reuses
`~/.config/huaweicloud/credentials.json`. Begin in read-only mode:

```bash
export HUAWEICLOUD_MCP_READ_ONLY="true"
uvx mcp-server-huaweicloud-gaussdb
```

Without devkit, set `HUAWEICLOUD_ACCESS_KEY`, `HUAWEICLOUD_SECRET_KEY`, and
`HUAWEICLOUD_REGION` explicitly as before.

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

Call `discover_create_options` or `list_instances` first to validate region, permissions, and project discovery. See the later sections for source installation, hot-reloaded credentials, and remote deployment.

## Category

Database / cloud resource management / operations automation.

## Features

- Create, inspect, resize, expand, and restart GaussDB instances.
- Discover project/domain context, engine versions, flavors, AZs, VPCs, subnets, and security groups.
- Select product type and a live-verified deployment form explicitly; discovery defaults to a basic single replica for development validation.
- Create and inspect backups and manage automatic backup policies.
- Inspect and update parameters, analyze slow SQL with epoch-millisecond or timezone-aware ISO
  8601 windows, and wait for asynchronous jobs with a bounded timeout.
- Reuse devkit S1 credentials or hot-reload AK/SK and temporary tokens from an MCP credential file.
- Read-only mode, block/confirm/warn rules, recursive masking, and JSONL audit output.

- Discover and batch-query instance, node and component monitoring metrics through CES.

## Available Tools

| Tool | Purpose | Risk | API documentation |
|---|---|---|---|
| `list_instances`, `get_instance` | Discover and inspect instances | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_328.html) |
| `list_flavors` | Find valid specifications | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_084.html) |
| `discover_create_options` | Discover all cloud prerequisites and a recommended create configuration | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `create_instance` | Provision an instance | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_017.html) |
| `delete_instance` | Permanently delete an instance after confirmation and a cloud-side protection recheck | DANGEROUS | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `resize_instance`, `expand_instance`, `restart_instance` | Manage instance capacity and lifecycle | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_019.html) |
| `get_instance_parameters`, `update_instance_parameters` | Inspect and update parameters | READ / WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `list_backups`, `get_backup_policy` | Inspect backups and policy | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_162.html) |
| `create_manual_backup`, `configure_backup_policy` | Create a backup or update policy | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `analyze_slow_sql` | Analyze performance using epoch-millisecond or timezone-aware ISO 8601 windows | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_297.html) |
| `get_job`, `wait_job` | Inspect one job state or poll to a terminal state with a bounded timeout | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `list_monitoring_metrics` | Discover live monitoring metrics and full dimensions | READ | [CES API](https://support.huaweicloud.com/intl/en-us/api-ces/ces_03_0023.html) |
| `query_monitoring_metrics` | Batch-query monitoring series and summaries | READ | [CES API](https://support.huaweicloud.com/intl/en-us/api-ces/ces_03_0034.html) |
| `list_openapi_operations`, `describe_openapi_operation` | Discover all public SDK operations and request shapes | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `invoke_read_openapi` | Invoke catalog-classified read operations | READ | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `invoke_write_openapi` | Invoke catalog-classified additive or reversible operations | WRITE | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |
| `invoke_dangerous_openapi` | Invoke destructive, disruptive, restore, upgrade, or billing-sensitive operations | DANGEROUS | [GaussDB API](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) |


### CES monitoring

1. Call `get_instance` for topology. Discover instance metrics with instance_id only, node metrics
   with an actual node_id, then component metrics with both node_id and a DN/CN component_id.
   Follow markers separately at each level. CES does not expand partial dimensions or wildcard IDs.
2. Pass selected items, including their complete ordered `dimensions`, to `query_monitoring_metrics`.
   The tool normalizes CES dimension order to instance, node, then component.
3. Use epoch milliseconds or timezone-aware ISO 8601 and select a period and aggregation. Up to
   20 series are queried per call, with the latest 20 displayed points per series by default.
   Summaries use all received in-window samples. Queries over the CES 3000-point budget are
   rejected with instructions to narrow the window, increase the period or split the batch.

Existing AK/SK, STS, region and Project ID are reused. Grant `ces:metrics:list` and
`ces:metricData:list` separately; GaussDB permissions alone do not grant CES access. Empty series
are marked `no_data`, never zero or healthy. `HUAWEICLOUD_CES_ENDPOINT` optionally overrides the
SDK regional endpoint. See [GaussDB metrics and collection constraints](https://support.huaweicloud.com/intl/en-us/usermanual-gaussdb/gaussdb_01_238.html).

### Complete OpenAPI access

At startup the server discovers public request operations from the installed Huawei Cloud GaussDB SDK. Version `0.5.1` discovers 265 request operations from SDK `3.1.218`, including versioned and compatibility operations. The catalog workflow keeps hundreds of schemas out of the model's always-on tool context: search with `list_openapi_operations`, inspect the recursive request structure with `describe_openapi_operation`, then use the matching risk-specific invocation tool.

The server rejects risk-lane mismatches. DANGEROUS calls always require `confirm=true`; when an `instance_id` is supplied, the server also re-reads the cloud resource and applies protected ID, name, and tag rules before invocation.

`attach_eip` only binds or unbinds an existing public IP. Use Huawei Cloud VPC/EIP
`CreatePublicip` (for example, `hcloud EIP CreatePublicip`) when allocation is needed, then pass
the returned address and public-IP ID to `attach_eip` and verify with `list_binded_eips`.

Use `wait_job` for long operations instead of repeated model-driven polling. A completed
`SWITCHDN` job can temporarily move the instance to `BACKING UP` while GaussDB creates an
automatic backup. Poll `get_instance` until the instance is `ACTIVE` before another write.

### Creation choices

Call `discover_create_options` first. Its MCP schema exposes `product_type` (`basic`, `enterprise`, or `ecology`), centralized `deployment_mode` (`single`, `triset`, or `logger`), distributed basic `combined`, distributed enterprise/ecology `hws`, and `ha_mode` (`centralization_standard` or `enterprise`). If deployment mode is omitted, the service derives it from the topology and product type.

The default is `basic + centralization_standard + single`, represented as `ha.instance_mode=basic`, `replica_num=1`, and one AZ entry. Single replica has no HA or SLA and is intended for development and functional testing. Production callers should explicitly select `triset` or a reviewed `logger` path.

The response separates common, centralized-only, and distributed-only parameters. Deployment templates, flavors, storage types, and AZs are queried for the active region and selected engine version. No regional flavor count or code is embedded in the server. `available_flavor_count`, `available`, and `flavors_truncated` describe each live result. Distributed basic queries the `combined` flavor family; distributed enterprise queries `enterprise`. For distributed modes, `availability_semantics=catalog_candidate` means the catalog has candidates, while Huawei Cloud still performs the final region, tenant, engine, and product binding check during creation.

The public v3.2 create request has no `solution` selector, so `logger` is live-discoverable but marked `direct_create_supported=false`; `create_instance` refuses to silently turn it into `triset`.

### Parameter update safety

`update_instance_parameters` always refreshes the instance's live parameter metadata through the current v3.2 API before a write. Unknown parameters and any parameter not explicitly returned with `readonly=false` are blocked. Each item reports `modifiable`, `read_only`, or `unknown`. The response previews old/new values, type, range, restart impact, and risk reasons. Clear boolean, numeric, enum, and range constraints are checked locally, with Huawei Cloud remaining the final validator. Restart-requiring or sensitive durability, security, replication, audit, memory, and connection-limit changes require a second call with `confirm=true`. Use `get_instance_parameters(modifiable_only=true)` to list only currently modifiable parameters. The generic OpenAPI channel blocks `update_instance_configuration` so these checks cannot be bypassed.

### Backup policy and tag request details

- `period` is a weekday list such as `1,3,5`. `differential_period` is a differential-backup interval in minutes and accepts only `15`, `30`, `60`, `180`, `360`, `720`, or `1440`.
- The read API returns `differential_period` as an integer while the generated write SDK model declares a string. The server normalizes reads to an integer and converts writes internally, so callers can pass a read value back directly.
- The deprecated cloud response spelling `differential_priod` is normalized to `differential_period`.
- When `differential_period` is omitted, the server reads the current policy and preserves its value automatically. This keeps the optional MCP input compatible with distributed instances, where the cloud API requires the field on update.
- Tag operations have different request shapes: `add_instance_tags` uses the `request.body.tags` array, while `delete_instance_tag` uses a top-level `key` beside `instance_id` and has no body. OpenAPI list and describe results include both request examples.

See the [GaussDB API overview](https://support.huaweicloud.com/api-gaussdb/gaussdb_api_007.html) and [permissions](https://support.huaweicloud.com/intl/en-us/api-gaussdb/gaussdb_api_188.html).

## Usage Guide

### Prerequisites

- Python 3.10 or later and [uv](https://docs.astral.sh/uv/) for UVX.
- A least-privilege IAM user with GaussDB API permissions.
- A Huawei Cloud region and AK/SK, preferably temporary credentials in production.

### Installation

After PyPI publication:

```bash
uvx mcp-server-huaweicloud-gaussdb
```

or:

```bash
pip install mcp-server-huaweicloud-gaussdb
mcp-server-huaweicloud-gaussdb
```

From source:

```bash
uvx --from "git+https://github.com/huaweicloud/huaweicloud-mcp.git#subdirectory=server/mcp_server_gaussdb" mcp-server-huaweicloud-gaussdb
```

The Git UVX form requires the shared core package to be published to PyPI first. For source changes, use the workspace:

```bash
git clone https://github.com/huaweicloud/huaweicloud-mcp.git
cd huaweicloud-mcp/server/mcp_server_gaussdb
uv sync --frozen
uv run mcp_server_gaussdb
```

This Python server uses the UVX/PIP distribution path and does not duplicate the implementation as an NPX package.

`mcp_server_gaussdb` is the repository-native command. The existing
`mcp-server-huaweicloud-gaussdb` command and distribution name are retained for compatibility;
both entrypoints start the same server package.

Source-checkout client configuration (also works with this integration branch before upstream merge):

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

## Configuration

Credential values resolve per field in this order: explicit environment variables, the MCP file
named by `HUAWEICLOUD_MCP_CREDENTIALS_FILE`, then the devkit S1 file at
`~/.config/huaweicloud/credentials.json`. The S1 keys `ak`, `sk`, `securityToken`, and `region`
map to the corresponding MCP settings. Override its path with
`HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE`, or disable reuse with
`HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS=1`. `HUAWEICLOUD_PROJECT_ID` remains optional and is
discovered through IAM when omitted; project and domain IDs are not read from devkit.

Project discovery uses `https://iam.myhuaweicloud.com` by default. Override it with `HUAWEICLOUD_IAM_ENDPOINT` for another Huawei Cloud partition or IAM endpoint.

For MCP-managed hot reload, set `HUAWEICLOUD_MCP_CREDENTIALS_FILE` to a mode-`0600` JSON file containing `access_key`, `secret_key`, `region`, and optional `project_id`, `domain_id`, and `security_token`. The devkit-owned file does not receive the MCP `0600` check, but must still be a regular JSON object. Both sources are re-read for every tool invocation.

Set `HUAWEICLOUD_MCP_READ_ONLY=true` to block writes. Use `HUAWEICLOUD_MCP_GUARDRAILS_CONFIG` for YAML rules and `HUAWEICLOUD_MCP_AUDIT_FILE` for an optional JSONL audit file. See the files under `examples/` and the [Chinese guide](README.md) for the full variable table and protection-boundary notes.

## Run with UVX

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

AgentArts supports UVX stdio and Streamable HTTP. See [Custom MCP access](https://support.huaweicloud.com/usermanual-agentarts0/agentarts_05_0136.html). To run remotely:

```bash
mcp-server-huaweicloud-gaussdb -t streamable-http
```

The default endpoint is `http://<host>:8000/mcp`. Put public deployments behind HTTPS and client authentication.

## Examples

A safe resize flow is: inspect the instance, list flavors, create and verify a backup, resize, then poll `get_job` until the asynchronous operation reaches a terminal state. If a guardrail requests confirmation, repeat the write call with `confirm=true` after review.

## Client compatibility

| Client or platform | Transport | Notes |
|---|---|---|
| AgentArts | UVX stdio / Streamable HTTP | Adapt the files under `examples/` |
| OfficeACE and CodeArts MCP Marketplace | Platform-supported stdio / Streamable HTTP | Listing fields and publication status follow each platform's process |
| Desktop clients such as Claude Desktop | stdio | The client must support `command`, `args`, and `env` configuration |
| Other standard MCP clients | stdio / Streamable HTTP | The remote endpoint is `/mcp` |

The server does not expose legacy SSE. It manages GaussDB cloud resources and does not open SQL sessions, execute arbitrary SQL, or provide natural-language-to-SQL features.

## Permissions

- Read-only discovery needs the GaussDB query APIs plus VPC, subnet, and security-group reads used by create-option discovery.
- Grant write permissions only for the enabled create, backup, resize, expansion, restart, or parameter tools.
- Prefer a separate principal or temporary grant for deletion, failover, restore, upgrade, and billing-sensitive APIs, together with MCP confirmation rules.
- Project auto-discovery requires IAM project-query permission. Supplying `HUAWEICLOUD_PROJECT_ID` avoids discovering another project for the selected region.

Map permissions to each enabled API using the official [permissions reference](https://support.huaweicloud.com/intl/en-us/api-gaussdb/gaussdb_api_188.html). Do not configure a long-lived administrator credential merely for convenience.

## Development, testing, and release

```bash
# From the repository root:
bash scripts/test.sh gaussdb
uv build --directory libs/huaweicloud_mcp_core
uv build --directory server/mcp_server_gaussdb
```

Default tests do not access cloud resources. Live validation must be explicitly enabled in a dedicated test account. Any billable resource must be cleaned up on failure as well as success, and its deletion job must reach a terminal state. Before release, also verify wheel metadata, installation in a clean Python 3.10 environment, the MCP tool list, and the absence of credentials or resource identifiers in deliverables.

## Contributing and support

See `CONTRIBUTING.md`, `SECURITY.md`, and `CHANGELOG.md` in the repository root. Use the GitHub issue templates for regular bugs and feature requests. Never disclose credentials or vulnerabilities in public issues.

## License

Apache License 2.0.
