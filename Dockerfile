FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY pyproject.toml uv.lock ./
COPY libs/huaweicloud_mcp_core ./libs/huaweicloud_mcp_core
COPY server/mcp_server_gaussdb ./server/mcp_server_gaussdb

RUN uv sync --frozen --package mcp-server-huaweicloud-gaussdb --no-dev

RUN useradd --system --uid 10001 mcp && chown -R mcp:mcp /app
USER mcp

ENV MCP_SERVER_HOST=0.0.0.0 \
    MCP_SERVER_PORT=8000
EXPOSE 8000

ENTRYPOINT ["uv", "run", "--frozen", "--no-sync", "mcp-server-huaweicloud-gaussdb"]
CMD ["-t", "streamable-http"]
