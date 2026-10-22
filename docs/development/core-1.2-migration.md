# Core 1.2 compatibility notes

The shared core remains backwards compatible with the existing RFS/RC services.

- `build_server` adds optional keyword-only `version` and `instructions` arguments.
- The root module additionally exports `clamp_limit`, `ProjectContext`,
  `resolve_project_context`, and `resolve_project_id`.
- `McpSettings` appends `domain_id`, `iam_endpoint`, and `credentials_file` fields.
- Credential precedence: environment variables → MCP credential file → devkit S1 file.
  Files are reread for each settings snapshot. MCP-owned files require private POSIX permissions;
  devkit files retain their existing permissions. Missing credentials use `MCP_CREDENTIAL_ERROR`.
- `HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE` overrides `~/.config/huaweicloud/credentials.json`;
  `HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS=1` disables the fallback.
- Project/domain discovery uses an account-scoped cache. An explicit project ID still avoids
  IAM lookup when only the project ID is required.
- DANGEROUS tools require `confirm=true`, including when no custom rule is configured.
- Existing masking markers, custom patterns, protection helpers, and audit APIs remain available.
  Masking additionally handles access-key fields; tag protection accepts API-style key/value arrays.

Each package retains its own path dependency and lock file. Existing service entrypoints remain valid.
