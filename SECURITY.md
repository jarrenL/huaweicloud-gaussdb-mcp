# Security Policy

## Supported versions

Security fixes are applied to the latest released minor version. Users should upgrade to the newest available release before reporting an issue that may already be fixed.

## Reporting a vulnerability

Do not open a public issue for a vulnerability or suspected credential exposure. Use the repository's private vulnerability-reporting function under **Security → Report a vulnerability**. If private reporting is unavailable, contact the repository maintainers through a private channel provided by the repository owner.

Include the affected version, impact, reproduction steps, and a minimal masked example. Do not include AK/SK values, security tokens, project/domain IDs, account details, resource IDs, private endpoints, or unredacted audit logs.

Maintainers should acknowledge a complete report, reproduce it in an isolated environment, assess affected versions, and coordinate a fix and disclosure. Public disclosure should wait until a corrected release is available.

## Credential exposure

If a Huawei Cloud credential may have been exposed, disable or rotate it immediately in IAM before collecting more evidence. Remove the value from local configuration and repository history, then inspect Cloud Trace Service and MCP audit records for unexpected activity.

## Deployment guidance

- Use a dedicated least-privilege IAM principal or temporary credentials.
- Keep stdio credentials in the client process environment or a mode-`0600` hot-reload file.
- Place Streamable HTTP behind HTTPS and client authentication; do not expose its default HTTP listener directly to the internet.
- Begin with `HUAWEICLOUD_MCP_READ_ONLY=true` and configure protected resources, confirmation rules, and audit output before enabling writes.
- Treat MCP tool output and audit files as sensitive operational data.
