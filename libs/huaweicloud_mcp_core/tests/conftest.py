# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# SPDX-License-Identifier: MIT

"""Shared test fixtures: clean environment for every test."""

from __future__ import annotations

import pytest

_ENV_KEYS = [
    "HUAWEICLOUD_MCP_CREDENTIALS_FILE",
    "HUAWEICLOUD_DEVKIT_CREDENTIALS_FILE",
    "HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS",
    "HUAWEICLOUD_DOMAIN_ID",
    "HUAWEICLOUD_IAM_ENDPOINT",
    "HUAWEICLOUD_ACCESS_KEY",
    "HUAWEICLOUD_SECRET_KEY",
    "HUAWEICLOUD_REGION",
    "HUAWEICLOUD_PROJECT_ID",
    "HUAWEICLOUD_SECURITY_TOKEN",
    "HUAWEICLOUD_ENDPOINT",
    "HUAWEICLOUD_MCP_READ_ONLY",
    "HUAWEICLOUD_MCP_PROTECTED_IDS",
    "HUAWEICLOUD_MCP_PROTECTED_NAMES",
    "HUAWEICLOUD_MCP_PROTECTED_TAGS",
    "HUAWEICLOUD_MCP_GUARDRAILS_CONFIG",
    "HUAWEICLOUD_MCP_AUDIT_FILE",
    "MCP_SERVER_PORT",
    "MCP_SERVER_HOST",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HUAWEICLOUD_SKIP_DEVKIT_CREDENTIALS", "1")
