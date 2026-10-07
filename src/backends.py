"""Chooses where the registry lives: the local JSON file (default) or Azure AI Search."""
from __future__ import annotations

import os

from .registry import DiscoveryResult, User, discover

_azure = None


def backend_name() -> str:
    return os.environ.get("REGISTRY_BACKEND", "local").strip().lower()


def discover_backend(query: str, user: User) -> DiscoveryResult:
    global _azure
    if backend_name() == "azure_search":
        from .search_registry import AzureSearchRegistry

        if _azure is None:
            _azure = AzureSearchRegistry()
        return _azure.discover(query, user)
    return discover(query, user)
