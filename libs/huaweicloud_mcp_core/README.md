# huaweicloud-mcp-core

Shared core library for all Huawei Cloud MCP servers in the `huaweicloud-mcp` monorepo.

## Responsibilities

- **config** — environment variables, MCP credential-file hot reload, and devkit S1 fallback (`McpSettings`)
- **credentials** — `BasicCredentials` / `GlobalCredentials` building with automatic
  project/domain resolution via IAM (account-scoped cache, overridable via `HUAWEICLOUD_PROJECT_ID`)
- **errors** — `McpToolError` and `wrap_sdk_error` for the unified error envelope
- **security** — `ToolRisk` (READ / WRITE / DANGEROUS) and the `@guard` decorator
- **guardrails** — `GuardrailsMiddleware` (read-only mode, resource protection rules,
  output masking, structured JSONL audit); auto-installed by `build_server()`
- **output** — paginated / single-object envelopes with token budget guards
- **server** — `build_server()` / `run_standard()` bootstrap (stdio + streamable-http)

## Usage

```python
from huaweicloud_mcp_core.server import build_server, run_standard

mcp = build_server("myservice")

from myservice.tools import thing  # noqa: F401  (import registers tools)


def main() -> None:
    run_standard(mcp, service_name="myservice")
```

See `docs/development/` in the repository root for the full specification.

Version 1.2.0 compatibility and credential configuration: [migration notes](../../docs/development/core-1.2-migration.md).

Version 1.3.0 keeps the existing credential sources and public helpers. AK/SK/STS are selected atomically; partial identities fail closed. HTTP defaults to loopback and public binds require a separate MCP access token plus Host allowlist. Error responses are masked and marked as errors, auditing is bounded/rotated, and `run_sdk_call` provides bounded SDK workers without automatic write retries. See the [GaussDB deployment notes](../../server/mcp_server_gaussdb/SECURITY.md) for settings and migration details.
