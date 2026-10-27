"""Thin asynchronous wrapper for read-only Cloud Eye monitoring APIs."""

import asyncio
import os
from typing import Any, cast

from huaweicloud_mcp_core import (
    CredentialScope,
    McpSettings,
    McpToolError,
    build_credentials,
    wrap_sdk_error,
)

from .gaussdb_client import sdk_to_dict


class CesMonitoringClient:
    def __init__(self, settings: McpSettings | None = None, sdk_client: Any = None) -> None:
        self._settings = settings or McpSettings.from_env()
        if sdk_client is not None:
            self._client = sdk_client
            return
        from huaweicloudsdkces.v1 import CesClient
        from huaweicloudsdkces.v1.region.ces_region import CesRegion
        from huaweicloudsdkcore.http.http_config import HttpConfig

        config = HttpConfig.get_default_config()
        config.timeout = 60
        builder = (
            CesClient.new_builder()
            .with_credentials(build_credentials(CredentialScope.PROJECT, self._settings))
            .with_http_config(config)
        )
        endpoint = os.getenv("HUAWEICLOUD_CES_ENDPOINT")
        if endpoint:
            builder = builder.with_endpoint(endpoint)
        else:
            builder = builder.with_region(CesRegion.value_of(self._settings.region))
        self._client = builder.build()

    async def _call(self, method: str, request: Any) -> dict[str, Any]:
        def invoke() -> dict[str, Any]:
            try:
                response = getattr(self._client, method)(request)
                return cast(dict[str, Any], sdk_to_dict(response))
            except Exception as exc:
                wrapped = wrap_sdk_error(exc)
                raise McpToolError(
                    wrapped.code,
                    wrapped.message,
                    request_id=wrapped.request_id,
                    hint=(
                        "Check CES permissions ces:metrics:list / ces:metricData:list in the "
                        "selected region and project. Use list_monitoring_metrics to obtain "
                        "current metric names and complete resource dimensions."
                    ),
                ) from exc

        return await asyncio.to_thread(invoke)

    async def list_metrics(
        self,
        *,
        namespace: str,
        dimensions: list[dict[str, str]],
        metric_name: str | None,
        limit: int,
        marker: str | None,
    ) -> dict[str, Any]:
        from huaweicloudsdkces.v1 import ListMetricsRequest

        dimension_args = {
            f"dim_{index}": f"{item['name']},{item['value']}"
            for index, item in enumerate(dimensions)
        }
        return await self._call(
            "list_metrics",
            ListMetricsRequest(
                namespace=namespace,
                metric_name=metric_name,
                limit=limit,
                start=marker,
                order="asc",
                **dimension_args,
            ),
        )

    async def batch_list_metric_data(
        self,
        *,
        metrics: list[dict[str, Any]],
        start_time: int,
        end_time: int,
        period: int,
        aggregation: str,
    ) -> dict[str, Any]:
        from huaweicloudsdkces.v1 import (
            BatchListMetricDataRequest,
            BatchListMetricDataRequestBody,
            MetricInfo,
            MetricsDimension,
        )

        body = BatchListMetricDataRequestBody(
            metrics=[
                MetricInfo(
                    namespace=item["namespace"],
                    metric_name=item["metric_name"],
                    dimensions=[MetricsDimension(**dimension) for dimension in item["dimensions"]],
                )
                for item in metrics
            ],
            period=str(period),
            filter=aggregation,
            _from=start_time,
            to=end_time,
        )
        return await self._call("batch_list_metric_data", BatchListMetricDataRequest(body=body))
