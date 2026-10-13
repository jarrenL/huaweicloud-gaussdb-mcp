"""Huawei Cloud project/global credentials and optional project discovery."""

from dataclasses import dataclass
from enum import Enum
from threading import Lock

from .config import McpSettings
from .errors import McpToolError, wrap_sdk_error


class CredentialScope(Enum):
    PROJECT = "project"
    GLOBAL = "global"


@dataclass(frozen=True)
class ProjectContext:
    project_id: str
    domain_id: str | None = None


_PROJECT_CACHE: dict[tuple[str, str], ProjectContext] = {}
_LOCK = Lock()


def reset_project_cache() -> None:
    with _LOCK:
        _PROJECT_CACHE.clear()


def _apply_token(credentials: object, token: str | None) -> object:
    return credentials.with_security_token(token) if token else credentials  # type: ignore[attr-defined]


def resolve_project_context(settings: McpSettings | None = None) -> ProjectContext:
    settings = settings or McpSettings.from_env()
    if settings.project_id and settings.domain_id:
        return ProjectContext(settings.project_id, settings.domain_id)
    cache_key = (settings.access_key, settings.region)
    with _LOCK:
        if cache_key in _PROJECT_CACHE:
            return _PROJECT_CACHE[cache_key]
    try:
        from huaweicloudsdkcore.auth.credentials import GlobalCredentials
        from huaweicloudsdkiam.v3 import IamClient, KeystoneListProjectsRequest

        credentials = _apply_token(
            GlobalCredentials(settings.access_key, settings.secret_key, settings.domain_id),
            settings.security_token,
        )
        response = (
            IamClient.new_builder()
            .with_credentials(credentials)
            .with_endpoint(settings.iam_endpoint)
            .build()
            .keystone_list_projects(KeystoneListProjectsRequest(name=settings.region))
        )
        projects = [
            project
            for project in (response.projects or [])
            if not settings.project_id or str(project.id) == settings.project_id
        ]
        if not projects or not projects[0].id:
            raise McpToolError("MCP_PROJECT_NOT_FOUND", "No project matched the configured region.")
        context = ProjectContext(
            project_id=str(projects[0].id),
            domain_id=str(projects[0].domain_id) if projects[0].domain_id else settings.domain_id,
        )
    except McpToolError:
        raise
    except Exception as exc:
        wrapped = wrap_sdk_error(exc)
        raise McpToolError(
            "MCP_PROJECT_NOT_FOUND",
            "Could not discover the Huawei Cloud project ID.",
            request_id=wrapped.request_id,
            hint="Set HUAWEICLOUD_PROJECT_ID from My Credentials > Project List.",
        ) from None
    with _LOCK:
        _PROJECT_CACHE[cache_key] = context
    return context


def resolve_project_id(settings: McpSettings | None = None) -> str:
    settings = settings or McpSettings.from_env()
    return settings.project_id or resolve_project_context(settings).project_id


def build_credentials(
    scope: CredentialScope = CredentialScope.PROJECT,
    settings: McpSettings | None = None,
) -> object:
    settings = settings or McpSettings.from_env()
    from huaweicloudsdkcore.auth.credentials import BasicCredentials, GlobalCredentials

    credentials: object
    if scope is CredentialScope.PROJECT:
        credentials = BasicCredentials(
            settings.access_key, settings.secret_key, resolve_project_id(settings)
        )
    else:
        credentials = GlobalCredentials(
            settings.access_key, settings.secret_key, settings.domain_id
        )
    return _apply_token(credentials, settings.security_token)
