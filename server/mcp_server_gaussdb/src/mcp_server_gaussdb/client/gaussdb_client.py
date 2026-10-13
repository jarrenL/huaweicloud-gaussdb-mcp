"""Thin asynchronous wrapper around GaussDBforopenGauss SDK v3."""

import asyncio
from typing import Any, cast

from huaweicloud_mcp_core import (
    CredentialScope,
    McpSettings,
    build_credentials,
    wrap_sdk_error,
)

_PRIMITIVES = {"str", "int", "float", "bool", "date", "datetime", "object"}
_SKIP_ATTRS = {"local_vars_configuration", "discriminator", "swagger_types", "openapi_types"}


def sdk_to_dict(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(key): sdk_to_dict(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sdk_to_dict(item) for item in obj]
    to_dict = getattr(obj, "to_dict", None)
    if callable(to_dict):
        return sdk_to_dict(to_dict())
    return {
        key.lstrip("_"): sdk_to_dict(value)
        for key, value in vars(obj).items()
        if key not in _SKIP_ATTRS and not key.startswith("__") and not callable(value)
    }


def _model_from_dict(module: Any, model: type[Any], values: dict[str, Any]) -> Any:
    reverse = {wire: attr for attr, wire in model.attribute_map.items()}

    def convert(type_name: str, value: Any) -> Any:
        if value is None:
            return None
        if type_name in _PRIMITIVES or type_name.startswith("dict("):
            return value
        if type_name.startswith("list["):
            return [convert(type_name[5:-1], item) for item in value]
        return _model_from_dict(module, getattr(module, type_name), value)

    kwargs = {}
    for key, value in values.items():
        attr = reverse.get(key, key)
        if attr not in model.openapi_types:
            raise ValueError(f"Unknown {model.__name__} field: {key}")
        kwargs[attr] = convert(model.openapi_types[attr], value)
    return model(**kwargs)


class GaussDBClient:
    def __init__(self, settings: McpSettings | None = None, sdk_client: Any = None) -> None:
        self._settings = settings or McpSettings.from_env()
        if sdk_client is not None:
            self._client = sdk_client
            return
        from huaweicloudsdkcore.http.http_config import HttpConfig
        from huaweicloudsdkgaussdbforopengauss.v3 import GaussDBforopenGaussClient

        endpoint = self._settings.endpoint or (
            f"https://gaussdb-opengauss.{self._settings.region}.myhuaweicloud.com"
        )
        config = HttpConfig.get_default_config()
        config.timeout = 60
        self._client = (
            GaussDBforopenGaussClient.new_builder()
            .with_credentials(build_credentials(CredentialScope.PROJECT, self._settings))
            .with_endpoint(endpoint)
            .with_http_config(config)
            .build()
        )

    async def _call(self, method: str, request: Any) -> dict[str, Any]:
        def invoke() -> dict[str, Any]:
            try:
                return cast(dict[str, Any], sdk_to_dict(getattr(self._client, method)(request)))
            except Exception as exc:
                raise wrap_sdk_error(exc) from exc

        return await asyncio.to_thread(invoke)

    async def invoke_openapi(self, *, operation: str, request: dict[str, Any]) -> dict[str, Any]:
        import huaweicloudsdkgaussdbforopengauss.v3 as sdk

        from ..openapi_catalog import get_operation

        metadata = get_operation(operation)
        if metadata is None:
            raise ValueError(f"Unknown GaussDB OpenAPI operation: {operation}")
        request_model = getattr(sdk, metadata.request_model)
        values = dict(request)
        if "x_language" in request_model.openapi_types and "x_language" not in values:
            values["x_language"] = "zh-cn"
        sdk_request = _model_from_dict(sdk, request_model, values)
        return await self._call(operation, sdk_request)

    async def list_database_instances(
        self, *, limit: int, offset: int, instance_id: str | None, name: str | None
    ) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import ListDatabaseInstancesRequest

        request = ListDatabaseInstancesRequest(
            x_language="zh-cn", id=instance_id, name=name, limit=limit, offset=offset
        )
        return await self._call("list_database_instances", request)

    async def list_flavors_details(
        self, *, version: str | None, ha_mode: str | None, limit: int, offset: int
    ) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import ListFlavorsDetailsRequest

        request = ListFlavorsDetailsRequest(
            x_language="zh-cn", version=version, ha_mode=ha_mode, limit=limit, offset=offset
        )
        return await self._call("list_flavors_details", request)

    async def list_datastores(self) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import ListDatastoresRequest

        return await self._call("list_datastores", ListDatastoresRequest(x_language="zh-cn"))

    async def show_deployment_form(
        self,
        *,
        solution: str,
        engine_version: str,
    ) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import ShowDeploymentFormRequest

        request = ShowDeploymentFormRequest(
            x_language="zh-cn",
            solution=solution,
            engine_version=engine_version,
        )
        return await self._call("show_deployment_form", request)

    async def list_storage_types(self, *, version: str, ha_mode: str) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import ListStorageTypesRequest

        request = ListStorageTypesRequest(x_language="zh-cn", version=version, ha_mode=ha_mode)
        return await self._call("list_storage_types", request)

    async def create_database_instance(self, *, body: dict[str, Any]) -> dict[str, Any]:
        import huaweicloudsdkgaussdbforopengauss.v3 as sdk

        request = sdk.CreateDatabaseInstanceRequest(
            x_language="zh-cn",
            body=_model_from_dict(sdk, sdk.CreateDatabaseInstanceRequestBody, body),
        )
        return await self._call("create_database_instance", request)

    async def delete_instance(self, *, instance_id: str) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import DeleteInstanceRequest

        request = DeleteInstanceRequest(x_language="zh-cn", instance_id=instance_id)
        return await self._call("delete_instance", request)

    async def create_manual_backup(
        self, *, instance_id: str, name: str, description: str | None
    ) -> dict[str, Any]:
        import huaweicloudsdkgaussdbforopengauss.v3 as sdk

        body = sdk.CreateManualBackupRequestBody(
            instance_id=instance_id, name=name, description=description
        )
        return await self._call(
            "create_manual_backup", sdk.CreateManualBackupRequest(x_language="zh-cn", body=body)
        )

    async def list_backups_details(
        self,
        *,
        instance_id: str,
        backup_type: str | None,
        begin_time: str | None,
        end_time: str | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import ListBackupsDetailsRequest

        request = ListBackupsDetailsRequest(
            x_language="zh-cn",
            instance_id=instance_id,
            backup_type=backup_type,
            begin_time=begin_time,
            end_time=end_time,
            limit=limit,
            offset=offset,
        )
        return await self._call("list_backups_details", request)

    async def resize_instances_flavor(
        self, *, instance_id: str, flavor_ref: str, is_auto_pay: bool
    ) -> dict[str, Any]:
        import huaweicloudsdkgaussdbforopengauss.v3 as sdk

        body = sdk.OpenGaussResizeRequestBody(flavor_ref=flavor_ref, is_auto_pay=is_auto_pay)
        request = sdk.ResizeInstancesFlavorRequest(
            x_language="zh-cn", instance_id=instance_id, body=body
        )
        return await self._call("resize_instances_flavor", request)

    async def run_instance_action(
        self, *, instance_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        import huaweicloudsdkgaussdbforopengauss.v3 as sdk

        request = sdk.RunInstanceActionRequest(
            x_language="zh-cn",
            instance_id=instance_id,
            body=_model_from_dict(sdk, sdk.OpenGaussInstanceActionRequest, body),
        )
        return await self._call("run_instance_action", request)

    async def restart_instance(self, *, instance_id: str) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import RestartInstanceRequest

        return await self._call(
            "restart_instance", RestartInstanceRequest(x_language="zh-cn", instance_id=instance_id)
        )

    async def show_instance_configuration(self, *, instance_id: str) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import (
            GaussDBforopenGaussClient,
            ShowInstanceConfigurationRequest,
        )

        request = ShowInstanceConfigurationRequest(x_language="zh-cn", instance_id=instance_id)
        if not isinstance(self._client, GaussDBforopenGaussClient):
            response = await self._call("show_instance_configuration", request)
            response["_metadata_api_version"] = "sdk-default-v3"
            return response

        def invoke_v32() -> dict[str, Any]:
            try:
                http_info = self._client._show_instance_configuration_http_info(request)
                http_info["resource_path"] = (
                    "/v3.2/{project_id}/instances/{instance_id}/configurations"
                )
                response = sdk_to_dict(self._client._call_api(**http_info))
                response["_metadata_api_version"] = "v3.2"
                return cast(dict[str, Any], response)
            except Exception as exc:
                raise wrap_sdk_error(exc) from exc

        return await asyncio.to_thread(invoke_v32)

    async def update_instance_configuration(
        self, *, instance_id: str, values: dict[str, str]
    ) -> dict[str, Any]:
        import huaweicloudsdkgaussdbforopengauss.v3 as sdk

        request = sdk.UpdateInstanceConfigurationRequest(
            x_language="zh-cn",
            instance_id=instance_id,
            body=sdk.OpenGaussModifyInstanceConfigurationRequest(values=values),
        )
        return await self._call("update_instance_configuration", request)

    async def list_slow_sqls(
        self,
        *,
        instance_id: str,
        node_ids: list[str],
        start_time: int,
        end_time: int,
        threshold: int,
    ) -> dict[str, Any]:
        import huaweicloudsdkgaussdbforopengauss.v3 as sdk

        body = sdk.ListSlowSqlsRequestBody(
            instance_id=instance_id,
            node_ids=node_ids,
            start_time=start_time,
            end_time=end_time,
            threshold=threshold,
        )
        request = sdk.ListSlowSqlsRequest(x_language="zh-cn", instance_id=instance_id, body=body)
        return await self._call("list_slow_sqls", request)

    async def show_job_detail(self, *, job_id: str) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import ShowJobDetailRequest

        return await self._call("show_job_detail", ShowJobDetailRequest(id=job_id))

    async def show_backup_policy(self, *, instance_id: str) -> dict[str, Any]:
        from huaweicloudsdkgaussdbforopengauss.v3 import ShowBackupPolicyRequest

        return await self._call(
            "show_backup_policy",
            ShowBackupPolicyRequest(x_language="zh-cn", instance_id=instance_id),
        )

    async def set_new_backup_policy(
        self, *, instance_id: str, policy: dict[str, Any]
    ) -> dict[str, Any]:
        import huaweicloudsdkgaussdbforopengauss.v3 as sdk

        body = sdk.SetNewBackupPolicyRequestBody(
            backup_policy=_model_from_dict(sdk, sdk.BackupPolicyInfoOption, policy)
        )
        request = sdk.SetNewBackupPolicyRequest(
            x_language="zh-cn", instance_id=instance_id, body=body
        )
        return await self._call("set_new_backup_policy", request)
