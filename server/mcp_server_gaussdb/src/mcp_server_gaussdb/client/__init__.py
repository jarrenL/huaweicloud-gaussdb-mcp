"""Huawei Cloud SDK adapters."""

from .gaussdb_client import GaussDBClient
from .vpc_client import VpcResourceClient

__all__ = ["GaussDBClient", "VpcResourceClient"]
