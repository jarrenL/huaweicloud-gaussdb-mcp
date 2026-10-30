# MCP 安装与配置

## 概述

本文用于安装 `mcp-server-huaweicloud-gaussdb`、把它注册到 MCP 客户端，并验证凭证读取。
当前 Skill 要求 MCP Server 不低于 `0.6.0`、Python 3.10+ 和 MCP Python SDK 2.x。运行时
`initialize` 与 `tools/list` 是版本和能力的权威来源。

## 安装方式

### 从源码工作区运行（当前可用）

```bash
git clone https://github.com/huaweicloud/huaweicloud-mcp.git
cd huaweicloud-mcp/server/mcp_server_gaussdb
uv sync --frozen
uv run mcp_server_gaussdb
```

MCP 客户端使用绝对路径注册：

```json
{
  "mcpServers": {
    "huaweicloud-gaussdb": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/huaweicloud-mcp/server/mcp_server_gaussdb",
        "mcp-server-huaweicloud-gaussdb"
      ],
      "env": {
        "HUAWEICLOUD_MCP_READ_ONLY": "true"
      }
    }
  }
}
```

### 从 PyPI 使用 UVX（发布后）

只有 PyPI 已同时发布 `huaweicloud-mcp-core>=1.2.0,<2` 和
`mcp-server-huaweicloud-gaussdb>=0.6.0,<1` 时，下面的命令才可直接使用：

```bash
uvx mcp-server-huaweicloud-gaussdb
```

不要把源码仓可以运行误报为 PyPI 已发布。发布前使用源码工作区模式。

## 凭证配置

凭证按字段使用以下优先级：

1. `HUAWEICLOUD_ACCESS_KEY`、`HUAWEICLOUD_SECRET_KEY`、
   `HUAWEICLOUD_SECURITY_TOKEN`、`HUAWEICLOUD_REGION`。
2. `HUAWEICLOUD_MCP_CREDENTIALS_FILE` 指向的 MCP 自管 JSON 文件。
3. `~/.config/huaweicloud/credentials.json` 中的 huaweicloud-devkit S1 凭证。

devkit 字段映射为：

| devkit S1 | MCP 设置 |
|---|---|
| `ak` | `access_key` |
| `sk` | `secret_key` |
| `securityToken` | `security_token` |
| `region` | `region` |

Project ID 和 Domain ID 不从 devkit S1 读取。缺少 Project ID 时，MCP 使用 IAM 项目列表
按区域自动发现。仅在自动发现无法唯一匹配时才设置 `HUAWEICLOUD_PROJECT_ID`。

可用的控制变量：

| 变量 | 用途 |
|---|---|
| `HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE` | 覆盖 devkit S1 默认路径 |
| `HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS=1` | 禁用 devkit 凭证回退 |
| `HUAWEICLOUD_MCP_READ_ONLY=true` | 阻断所有 WRITE 和 DANGEROUS 工具 |
| `HUAWEICLOUD_MCP_GUARDRAILS_CONFIG` | 指定安全护栏 YAML |
| `HUAWEICLOUD_MCP_PROTECTED_IDS` | 保护资源 ID，逗号分隔 |
| `HUAWEICLOUD_MCP_PROTECTED_NAMES` | 保护资源名称，逗号分隔 |
| `HUAWEICLOUD_MCP_PROTECTED_TAGS` | 保护标签，例如 `environment=production` |
| `HUAWEICLOUD_MCP_AUDIT_FILE` | JSONL 审计文件路径 |

MCP 自管凭证文件在 Linux/macOS 上必须是普通文件且权限为 `0600`。devkit S1 由 devkit 管理，
读取时不强制 `0600`。两种文件都会在每次工具调用时重新读取，因此凭证轮换无需重启 MCP。

## 安全要求

✅ 正确：

- 在客户端环境或受控凭证文件中配置凭证。
- 优先使用 IAM 用户或临时 SecurityToken。
- 先启用只读模式完成联通验证。

❌ 错误：

- 让用户在对话中粘贴 AK/SK、SecurityToken 或数据库密码。
- 把真实凭证写入 MCP 配置示例、Skill、脚本或 Git 仓库。
- 通过打印环境变量检查凭证内容。

## 验证

1. 启动 MCP 后确认客户端能列出工具。
2. 调用 `list_instances(limit=1)`；无实例时空列表也表示认证和区域路由成功。
3. 调用 `discover_create_options(limit=1)` 验证 IAM Project 自动发现与 VPC 只读权限。
4. 保持只读模式，确认 `create_instance` 被护栏拒绝。

如果返回 `MCP_CREDENTIAL_ERROR`，只检查凭证来源是否存在、字段名、region 和文件权限，不输出
任何凭证值。如果返回权限错误，按 `iam-policies.md` 补充最小权限后再验证。
