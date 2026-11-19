# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""GaussDB credential scoping and regional IAM context discovery."""

from __future__ import annotations

import threading
from dataclasses import dataclass, replace

from huaweicloud_mcp_core.credentials import CredentialScope
from huaweicloud_mcp_core.credentials import build_credentials as build_core_credentials
from huaweicloud_mcp_core.errors import McpToolError, wrap_sdk_error
from huaweicloudsdkcore.auth.credentials import BasicCredentials, GlobalCredentials

from .settings import McpSettings


@dataclass(frozen=True)
class ProjectContext:
    """IAM project and the account that owns it."""

    project_id: str
    domain_id: str | None = None


_PROJECT_CACHE: dict[tuple[str, str, str, str | None, str | None], ProjectContext] = {}
_CACHE_LOCK = threading.Lock()


def resolve_project_context(settings: McpSettings | None = None) -> ProjectContext:
    """Resolve regional project and its owning domain with an account-scoped cache."""
    settings = settings or McpSettings.from_env()
    if settings.project_id and settings.domain_id:
        return ProjectContext(settings.project_id, settings.domain_id)
    cache_key = (
        settings.access_key,
        settings.region,
        settings.iam_endpoint,
        settings.project_id,
        settings.domain_id,
    )
    with _CACHE_LOCK:
        cached = _PROJECT_CACHE.get(cache_key)
    if cached:
        return cached

    from huaweicloudsdkcore.http.http_config import HttpConfig
    from huaweicloudsdkiam.v3 import IamClient, KeystoneListProjectsRequest

    credentials = GlobalCredentials().with_ak(settings.access_key).with_sk(settings.secret_key)
    if settings.security_token:
        credentials = credentials.with_security_token(settings.security_token)
    client = (
        IamClient.new_builder()
        .with_credentials(credentials)
        .with_endpoint(settings.iam_endpoint)
        .with_http_config(HttpConfig(timeout=(10, 30), retry_times=0))
        .build()
    )
    try:
        response = client.keystone_list_projects(KeystoneListProjectsRequest(name=settings.region))
    except Exception as exc:
        wrapped = wrap_sdk_error(exc)
        raise McpToolError(
            code=wrapped.code,
            message=(
                f"Failed to resolve project_id for region '{settings.region}' "
                f"via IAM: {wrapped.message}"
            ),
            request_id=wrapped.request_id,
            hint=(
                "The AK/SK may lack IAM read permission. Set HUAWEICLOUD_PROJECT_ID "
                "manually (console: My Credentials > Project List)."
            ),
        ) from exc
    projects = [
        project
        for project in (response.projects or [])
        if not settings.project_id or str(project.id) == settings.project_id
    ]
    if not projects or not projects[0].id:
        raise McpToolError(
            code="MCP_PROJECT_NOT_FOUND",
            message=f"No IAM project found for region '{settings.region}'.",
            hint="Set HUAWEICLOUD_PROJECT_ID explicitly (console: My Credentials > Project List).",
        )
    domain_id = getattr(projects[0], "domain_id", None)
    context = ProjectContext(
        str(projects[0].id), str(domain_id) if domain_id else settings.domain_id
    )
    with _CACHE_LOCK:
        _PROJECT_CACHE[cache_key] = context
    return context


def resolve_project_id(settings: McpSettings | None = None) -> str:
    """Retain the project-ID-only API and explicit-ID IAM short circuit."""
    settings = settings or McpSettings.from_env()
    return settings.project_id or resolve_project_context(settings).project_id


def build_credentials(
    scope: CredentialScope = CredentialScope.PROJECT,
    settings: McpSettings | None = None,
) -> BasicCredentials | GlobalCredentials:
    """Build SDK credentials for the requested scope, sharing a common settings source."""
    settings = settings or McpSettings.from_env()
    if scope is not CredentialScope.GLOBAL and not settings.project_id:
        # Pass the discovered ID explicitly to bypass core 1.0's region-only IAM cache.
        settings = replace(settings, project_id=resolve_project_id(settings))
    credentials = build_core_credentials(scope=scope, settings=settings)
    if isinstance(credentials, GlobalCredentials) and settings.domain_id:
        return credentials.with_domain_id(settings.domain_id)
    return credentials


def reset_project_cache() -> None:
    """Clear cached IAM contexts."""
    with _CACHE_LOCK:
        _PROJECT_CACHE.clear()
