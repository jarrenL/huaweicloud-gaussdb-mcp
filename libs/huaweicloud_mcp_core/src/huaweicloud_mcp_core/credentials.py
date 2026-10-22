# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Credential building with automatic project_id resolution."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum

from huaweicloudsdkcore.auth.credentials import BasicCredentials, GlobalCredentials

from huaweicloud_mcp_core.config import McpSettings
from huaweicloud_mcp_core.errors import McpToolError

_IAM_ENDPOINT = "https://iam.myhuaweicloud.com"


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    domain_id: str | None = None


_PROJECT_CACHE: dict[tuple[str, str, str, str | None, str | None], ProjectContext] = {}
_CACHE_LOCK = threading.Lock()


class CredentialScope(Enum):
    PROJECT = "project"
    GLOBAL = "global"


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

    from huaweicloudsdkiam.v3 import IamClient, KeystoneListProjectsRequest

    credentials = GlobalCredentials().with_ak(settings.access_key).with_sk(settings.secret_key)
    if settings.security_token:
        credentials = credentials.with_security_token(settings.security_token)
    client = (
        IamClient.new_builder()
        .with_credentials(credentials)
        .with_endpoint(settings.iam_endpoint)
        .build()
    )
    try:
        response = client.keystone_list_projects(KeystoneListProjectsRequest(name=settings.region))
    except Exception as exc:
        from huaweicloud_mcp_core.errors import wrap_sdk_error

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
    if scope is CredentialScope.GLOBAL:
        credentials: BasicCredentials | GlobalCredentials = (
            GlobalCredentials().with_ak(settings.access_key).with_sk(settings.secret_key)
        )
        if settings.domain_id:
            credentials = credentials.with_domain_id(settings.domain_id)
        if settings.security_token:
            credentials = credentials.with_security_token(settings.security_token)
        return credentials
    credentials = BasicCredentials().with_ak(settings.access_key).with_sk(settings.secret_key)
    if settings.security_token:
        credentials = credentials.with_security_token(settings.security_token)
    return credentials.with_project_id(resolve_project_id(settings))


def reset_project_cache() -> None:
    with _CACHE_LOCK:
        _PROJECT_CACHE.clear()
