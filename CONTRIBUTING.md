# Contributing

Thank you for contributing to Huawei Cloud Database MCP. The current repository scope is GaussDB. Proposals for other database engines should be discussed separately so their API, credentials, permissions, and lifecycle behavior can be reviewed independently.

## Before opening a change

1. Search existing issues and pull requests.
2. For a new public tool, describe the user scenario, Huawei Cloud API, request/response mapping, IAM actions, risk level, and cleanup behavior.
3. Never include real AK/SK values, security tokens, project/domain IDs, instance IDs, IP addresses, account details, or unmasked cloud responses.

## Local setup

```bash
uv sync --frozen --all-packages --all-groups
```

Run static checks, tests, and builds before submitting:

```bash
uv run --package huaweicloud-mcp-core ruff check libs/huaweicloud_mcp_core/src libs/huaweicloud_mcp_core/tests
uv run --package mcp-server-huaweicloud-gaussdb ruff check server/mcp_server_gaussdb/src server/mcp_server_gaussdb/tests
(cd libs/huaweicloud_mcp_core && uv run --package huaweicloud-mcp-core mypy src tests)
(cd server/mcp_server_gaussdb && uv run --package mcp-server-huaweicloud-gaussdb mypy src)
uv run --package huaweicloud-mcp-core pytest libs/huaweicloud_mcp_core/tests
uv run --package mcp-server-huaweicloud-gaussdb pytest server/mcp_server_gaussdb/tests
uv build --package huaweicloud-mcp-core
uv build --package mcp-server-huaweicloud-gaussdb
```

## Design rules

- Keep MCP tools scenario-oriented. Use the OpenAPI catalog path for long-tail APIs instead of registering hundreds of always-on tool schemas.
- Put MCP argument handling and guard decorators in `tools`, orchestration in `service`, and Huawei Cloud SDK calls in `client`.
- Classify every operation as READ, WRITE, or DANGEROUS. Deletion, service interruption, restore, failover, upgrade, and billing-sensitive calls belong in DANGEROUS.
- Discover region-dependent values from Huawei Cloud APIs. Do not hard-code flavor counts, flavor codes, availability zones, deployment availability, or engine-version availability.
- Validate write inputs against live metadata where the service exposes it. Unknown or ambiguous safety metadata should fail closed.
- Return the shared output envelope and let the common runtime mask sensitive values and write audit events.
- Preserve credential hot reload. Clients and services must obtain credentials through the shared credential provider for each call.

## Testing

Unit tests must cover request mapping, pagination, malformed inputs, API errors, guardrails, and sensitive-field masking. Default tests must not call Huawei Cloud.

Live validation is opt-in. Use a dedicated non-production account, the lowest-cost supported configuration, explicit resource tags, and a cleanup block that runs even when validation fails. Confirm asynchronous deletion reaches a terminal state and record only masked evidence.

## Documentation and versioning

Update the Chinese and English service README files when tools, configuration, behavior, or compatibility changes. Add a changelog entry for user-visible changes and bump the package version according to semantic versioning. Keep `uv.lock` committed after dependency or version changes.

## Pull requests

Keep each pull request focused. Explain the trigger, resulting behavior, security/risk classification, tests, and any live validation. A reviewer should be able to assess the change without access to internal conversations or credentials.
