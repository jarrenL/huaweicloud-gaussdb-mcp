"""Thin asynchronous wrapper around the Huawei Cloud VPC SDK."""

import asyncio
from typing import Any, cast

from huaweicloud_mcp_core import CredentialScope, McpSettings, build_credentials, wrap_sdk_error

from .gaussdb_client import sdk_to_dict


class VpcResourceClient:
    def __init__(self, settings: McpSettings | None = None, sdk_client: Any = None) -> None:
        self._settings = settings or McpSettings.from_env()
        if sdk_client is not None:
            self._client = sdk_client
            return
        from huaweicloudsdkvpc.v2 import VpcClient

        endpoint = f"https://vpc.{self._settings.region}.myhuaweicloud.com"
        self._client = (
            VpcClient.new_builder()
            .with_credentials(build_credentials(CredentialScope.PROJECT, self._settings))
            .with_endpoint(endpoint)
            .build()
        )

    async def _call(self, method: str, request: Any) -> dict[str, Any]:
        def invoke() -> dict[str, Any]:
            try:
                return cast(dict[str, Any], sdk_to_dict(getattr(self._client, method)(request)))
            except Exception as exc:
                raise wrap_sdk_error(exc) from exc

        return await asyncio.to_thread(invoke)

    async def list_vpcs(self, *, limit: int = 100) -> dict[str, Any]:
        from huaweicloudsdkvpc.v2 import ListVpcsRequest

        return await self._call("list_vpcs", ListVpcsRequest(limit=limit))

    async def list_subnets(self, *, limit: int = 100) -> dict[str, Any]:
        from huaweicloudsdkvpc.v2 import ListSubnetsRequest

        return await self._call("list_subnets", ListSubnetsRequest(limit=limit))

    async def list_security_groups(self, *, limit: int = 100) -> dict[str, Any]:
        from huaweicloudsdkvpc.v2 import ListSecurityGroupsRequest

        return await self._call("list_security_groups", ListSecurityGroupsRequest(limit=limit))
