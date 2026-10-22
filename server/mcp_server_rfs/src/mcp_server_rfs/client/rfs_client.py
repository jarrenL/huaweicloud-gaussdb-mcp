# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Thin SDK wrapper for huaweicloudsdkrfs. No business logic here."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, cast

from huaweicloud_mcp_core.config import McpSettings
from huaweicloud_mcp_core.credentials import CredentialScope, build_credentials
from huaweicloud_mcp_core.errors import wrap_sdk_error
from huaweicloudsdkcore.exceptions.exceptions import ServiceResponseException
from huaweicloudsdkrfs.v1 import RfsClient as _SdkRfsClient
from huaweicloudsdkrfs.v1.model.create_execution_plan_request import CreateExecutionPlanRequest
from huaweicloudsdkrfs.v1.model.create_execution_plan_request_body import (
    CreateExecutionPlanRequestBody,
)
from huaweicloudsdkrfs.v1.model.create_stack_request import CreateStackRequest
from huaweicloudsdkrfs.v1.model.create_stack_request_body import CreateStackRequestBody
from huaweicloudsdkrfs.v1.model.delete_stack_enhanced_request import DeleteStackEnhancedRequest
from huaweicloudsdkrfs.v1.model.delete_stack_enhanced_request_body import (
    DeleteStackEnhancedRequestBody,
)
from huaweicloudsdkrfs.v1.model.deploy_stack_request import DeployStackRequest
from huaweicloudsdkrfs.v1.model.deploy_stack_request_body import DeployStackRequestBody
from huaweicloudsdkrfs.v1.model.get_execution_plan_metadata_request import (
    GetExecutionPlanMetadataRequest,
)
from huaweicloudsdkrfs.v1.model.get_execution_plan_request import GetExecutionPlanRequest
from huaweicloudsdkrfs.v1.model.get_stack_metadata_request import GetStackMetadataRequest
from huaweicloudsdkrfs.v1.model.list_stack_events_request import ListStackEventsRequest
from huaweicloudsdkrfs.v1.model.list_stack_outputs_request import ListStackOutputsRequest
from huaweicloudsdkrfs.v1.model.list_stack_resources_request import ListStackResourcesRequest
from huaweicloudsdkrfs.v1.model.list_stacks_request import ListStacksRequest
from huaweicloudsdkrfs.v1.model.vars_structure import VarsStructure
from huaweicloudsdkrfs.v1.region.rfs_region import RfsRegion

_SKIP_ATTRS = {
    "local_vars_configuration",
    "discriminator",
    "swagger_types",
    # SdkResponse transport-layer fields, set on every SDK response object:
    #   _raw_content -> bytes (the raw HTTP body); not part of the logical
    #     response and not JSON-serializable, so never leak it into tool output.
    #   _status_code -> int; HTTP transport metadata, not a response field.
    "_raw_content",
    "_status_code",
}


def _new_client_request_id() -> str:
    """Generate a unique Client-Request-Id for RFS API tracing.

    RFS APIGW requires a standard UUID (36 chars, dashed form 8-4-4-4-12);
    the 32-char hex form is rejected with RF.10011006.
    """
    return str(uuid.uuid4())


def sdk_to_dict(obj: Any) -> Any:
    """Recursively convert an SDK response object into plain JSON-compatible data."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(key): sdk_to_dict(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sdk_to_dict(item) for item in obj]
    # Defensive guard: some leaf types carried by SDK responses have no
    # __dict__ (bytes via _raw_content, datetime, Decimal, enums, ...). Skip
    # name-filtered transport fields above; for anything else without
    # __dict__, coerce to str so the result stays JSON-serializable instead of
    # raising "vars() argument must have __dict__ attribute".
    if not hasattr(obj, "__dict__"):
        return str(obj)
    result: dict[str, Any] = {}
    for key, value in vars(obj).items():
        if key in _SKIP_ATTRS or key.startswith("__") or callable(value):
            continue
        result[key.lstrip("_")] = sdk_to_dict(value)
    return result


def _vars_structure(variables: dict[str, str] | None) -> list[VarsStructure]:
    return [
        VarsStructure(var_key=str(key), var_value=str(value))
        for key, value in (variables or {}).items()
    ]


class RfsClient:
    """Async wrapper around the synchronous huaweicloudsdkrfs client."""

    def __init__(
        self,
        settings: McpSettings | None = None,
        sdk_client: Any = None,
    ) -> None:
        self._settings = settings or McpSettings.from_env()
        if sdk_client is not None:
            self._client = sdk_client
        else:
            self._client = (
                _SdkRfsClient.new_builder()
                .with_credentials(build_credentials(CredentialScope.PROJECT, self._settings))
                .with_region(RfsRegion.value_of(self._settings.region))
                .build()
            )

    async def list_stacks(self, *, limit: int, marker: str | None) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            request = ListStacksRequest(
                client_request_id=_new_client_request_id(), limit=limit, marker=marker
            )
            return cast(dict[str, Any], sdk_to_dict(self._client.list_stacks(request)))

        return await asyncio.to_thread(_call)

    async def get_stack_metadata(self, stack_name: str) -> dict[str, Any] | None:
        def _call() -> dict[str, Any] | None:
            request = GetStackMetadataRequest(
                client_request_id=_new_client_request_id(), stack_name=stack_name
            )
            try:
                response = self._client.get_stack_metadata(request)
            except ServiceResponseException as exc:
                if exc.status_code == 404:
                    return None
                raise wrap_sdk_error(exc) from exc
            return cast(dict[str, Any], sdk_to_dict(response))

        return await asyncio.to_thread(_call)

    async def create_stack(
        self,
        *,
        stack_name: str,
        template_body: str | None,
        template_uri: str | None,
        variables: dict[str, str] | None,
        enable_deletion_protection: bool,
        description: str | None = None,
    ) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            body = CreateStackRequestBody(
                stack_name=stack_name,
                template_body=template_body,
                template_uri=template_uri,
                vars_structure=_vars_structure(variables),
                enable_deletion_protection=enable_deletion_protection,
                description=description,
            )
            request = CreateStackRequest(client_request_id=_new_client_request_id(), body=body)
            return cast(dict[str, Any], sdk_to_dict(self._client.create_stack(request)))

        return await asyncio.to_thread(_call)

    async def deploy_stack(
        self,
        *,
        stack_name: str,
        template_body: str | None,
        template_uri: str | None,
        variables: dict[str, str] | None,
    ) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            body = DeployStackRequestBody(
                template_body=template_body,
                template_uri=template_uri,
                vars_structure=_vars_structure(variables),
            )
            request = DeployStackRequest(
                client_request_id=_new_client_request_id(), stack_name=stack_name, body=body
            )
            return cast(dict[str, Any], sdk_to_dict(self._client.deploy_stack(request)))

        return await asyncio.to_thread(_call)

    async def delete_stack(self, *, stack_name: str, retain_all_resources: bool) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            body = DeleteStackEnhancedRequestBody(retain_all_resources=retain_all_resources)
            request = DeleteStackEnhancedRequest(
                client_request_id=_new_client_request_id(), stack_name=stack_name, body=body
            )
            return cast(dict[str, Any], sdk_to_dict(self._client.delete_stack_enhanced(request)))

        return await asyncio.to_thread(_call)

    async def list_stack_events(
        self,
        *,
        stack_name: str,
        limit: int,
        marker: str | None = None,
    ) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            request = ListStackEventsRequest(
                client_request_id=_new_client_request_id(),
                stack_name=stack_name,
                limit=limit,
                marker=marker,
            )
            return cast(dict[str, Any], sdk_to_dict(self._client.list_stack_events(request)))

        return await asyncio.to_thread(_call)

    async def list_stack_resources(self, *, stack_name: str) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            request = ListStackResourcesRequest(
                client_request_id=_new_client_request_id(), stack_name=stack_name
            )
            return cast(dict[str, Any], sdk_to_dict(self._client.list_stack_resources(request)))

        return await asyncio.to_thread(_call)

    async def list_stack_outputs(self, *, stack_name: str) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            request = ListStackOutputsRequest(
                client_request_id=_new_client_request_id(), stack_name=stack_name
            )
            return cast(dict[str, Any], sdk_to_dict(self._client.list_stack_outputs(request)))

        return await asyncio.to_thread(_call)

    async def create_execution_plan(
        self,
        *,
        stack_name: str,
        template_body: str | None,
        template_uri: str | None,
        variables: dict[str, str] | None,
    ) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            body = CreateExecutionPlanRequestBody(
                template_body=template_body,
                template_uri=template_uri,
                vars_structure=_vars_structure(variables),
            )
            request = CreateExecutionPlanRequest(
                client_request_id=_new_client_request_id(), stack_name=stack_name, body=body
            )
            return cast(dict[str, Any], sdk_to_dict(self._client.create_execution_plan(request)))

        return await asyncio.to_thread(_call)

    async def get_execution_plan_metadata(
        self,
        *,
        stack_name: str,
        execution_plan_id: str,
    ) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            request = GetExecutionPlanMetadataRequest(
                client_request_id=_new_client_request_id(),
                stack_name=stack_name,
                execution_plan_id=execution_plan_id,
            )
            return cast(
                dict[str, Any], sdk_to_dict(self._client.get_execution_plan_metadata(request))
            )

        return await asyncio.to_thread(_call)

    async def get_execution_plan(
        self,
        *,
        stack_name: str,
        execution_plan_id: str,
    ) -> dict[str, Any]:
        def _call() -> dict[str, Any]:
            request = GetExecutionPlanRequest(
                client_request_id=_new_client_request_id(),
                stack_name=stack_name,
                execution_plan_id=execution_plan_id,
            )
            return cast(dict[str, Any], sdk_to_dict(self._client.get_execution_plan(request)))

        return await asyncio.to_thread(_call)
