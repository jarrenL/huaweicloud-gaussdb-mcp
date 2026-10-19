# Changelog

All notable user-visible changes are recorded here. This project follows semantic versioning.

## [0.3.7] - 2026-10-19

### Added

- Reused credentials managed by `huaweicloud-devkit` from
  `~/.config/huaweicloud/credentials.json`, including temporary security tokens and region.
- Added `HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE` for a custom devkit S1 path and
  `HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS=1` to disable automatic reuse.

### Changed

- Credential values now resolve per field in this order: explicit environment variable, MCP
  credential file, then the devkit S1 store. Project and domain IDs continue to use explicit
  configuration or IAM discovery.
- The MCP-owned credential file still requires mode `0600`; the devkit-owned S1 file accepts its
  existing permissions while retaining regular-file and JSON-object validation.

## [0.3.6] - 2026-10-09

### Fixed

- Preserved the current `differential_period` automatically when callers omit it from `configure_backup_policy`; distributed instances require the field even though the public model marks it optional.
- Clarified that distributed flavor and storage discovery returns catalog candidates rather than proof of the final region, tenant, engine, and product binding.
- Added actionable hints for distributed create failures `DBS.200054` and `DBS.06280045` without hard-coding regional availability.

### Validation

- Added the sanitized Guiyang 1 enterprise `hws` distributed end-to-end report and corrected the reusable verification script to the current MCP argument schemas.
- Expanded regression coverage for create-parameter safety, parameter-range validation, node-discovery degradation, OpenAPI request errors, SDK error wrapping, credential hot reload, IAM project discovery, guardrail failure modes, and both transports. The GaussDB package now passes 42 default tests at 97.34% coverage; the shared core passes 15 tests at 98.51% coverage. The 13 explicitly enabled live-cloud tests remain skipped by default. Both packages now enforce a 90% minimum coverage threshold instead of 80%.

## [0.3.5] - 2026-10-09

### Fixed

- Normalized `get_backup_policy` to return `differential_period` as integer minutes and absorb the deprecated cloud response spelling `differential_priod`.
- Changed `configure_backup_policy.differential_period` to an integer-minute schema, validated the supported values `15`, `30`, `60`, `180`, `360`, `720`, and `1440`, and converted to the generated SDK's string write model internally.
- Added local weekday validation for the full-backup `period` field.
- Added request-shape guidance and examples for `add_instance_tags` and `delete_instance_tag`; malformed delete requests with a body now fail locally with the correct top-level query shape.

## [0.3.4] - 2026-10-09

### Fixed

- Switched instance-parameter discovery from the deprecated v3 endpoint to the current v3.2 endpoint. Beijing 4 live validation returned 519 modifiable parameters, 2 read-only parameters, and no unknown modifiability values.
- Added explicit `modifiable`, `read_only`, and `unknown` parameter states while preserving fail-closed behavior when Huawei Cloud omits the `readonly` field.
- Added node IDs and node summaries to `get_instance`, so `analyze_slow_sql` no longer requires a generic OpenAPI lookup.
- Populated `serverInfo.version` with the package version.

### Security

- Blocked `update_instance_configuration` through the generic OpenAPI write channel. Parameter changes must use `update_instance_parameters`, which enforces live metadata, range validation, restart impact, sensitive-parameter confirmation, masking, and audit controls.

### Changed

- OpenAPI discovery now states the `snake_case` naming convention, exact invocation argument names, and dedicated-tool restrictions.
- Tool descriptions now include concrete millisecond timestamp and request-object examples.

## [0.3.3] - 2026-10-09

### Added

- Public-repository landing pages with quick start, client configuration, security guidance, scope, development, and support information.
- Contribution and security policies, changelog, issue templates, and pull request template.
- Clear client compatibility and least-privilege guidance aligned with the documented GaussDB behavior.

### Changed

- Reorganized the GaussDB documentation around the same practical flow used by the PolarDB reference: overview, prerequisites, quick start, capabilities, configuration, development, support, and license.
- Clarified that this implementation uses stdio and Streamable HTTP and does not claim unsupported SQL execution, text-to-SQL, legacy SSE, or completed marketplace publication.

## [0.3.2] - 2026-10-08

### Added

- Live preflight for parameter changes, including modifiability, type/range, restart impact, and sensitive-parameter confirmation.
- `modifiable_only` parameter discovery and masked live-validation evidence.

## [0.3.1] - 2026-10-08

### Added

- Dynamic create-option discovery for centralized and distributed variants.
- Product-edition handling for basic, enterprise, and ecology deployment paths.
- Live, paginated regional flavor discovery without hard-coded counts or specification codes.

## [0.3.0] - 2026-10-08

### Added

- Catalog access to all public request operations discovered from the installed GaussDB SDK.
- Risk-separated READ, WRITE, and DANGEROUS invocation tools.
- Generic client-neutral offline delivery package.
