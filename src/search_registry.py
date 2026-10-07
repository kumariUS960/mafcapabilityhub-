"""Azure AI Search as the Capability Registry.

Turn it on with:  REGISTRY_BACKEND=azure_search   (plus AZURE_SEARCH_ENDPOINT, optional AZURE_SEARCH_INDEX)

Design points from the guide:
* Azure AI Search is the DISCOVERY layer only. It never runs a capability.
* Security trimming happens INSIDE the search query (an OData filter on allowed groups and status),
  so capabilities a user may not use are not even returned for exposure to the agent.
* The full registry record is stored as JSON in a 'payload' field, so the resolution layer
  gets the same dict shape as with the local JSON registry.

IMPORTANT: this module could not be run against a real Azure AI Search service when it was written.
The filter builder and record mapping are unit tested; the live calls are not. Expect to adjust
once, and give your identity the roles listed in the README.
"""
from __future__ import annotations

import json
import os

from .registry import DiscoveryResult, User

DEFAULT_INDEX = "capability-registry"


def build_group_filter(groups: tuple[str, ...] | list[str]) -> str:
    """OData filter: only ACTIVE capabilities that share at least one group with the user.

    This is the standard 'security trimming' pattern for Azure AI Search.
    """
    if not groups:
        return "status eq 'active' and false"  # a user with no groups can use nothing
    joined = ",".join(g.replace("'", "''") for g in groups)
    return f"status eq 'active' and allowed_groups/any(g: search.in(g, '{joined}', ','))"


def record_to_document(cap: dict) -> dict:
    """Registry record -> search document. The full record rides along in 'payload'."""
    return {
        "id": cap["id"],
        "name": cap["name"],
        "description": cap["description"],
        "keywords": cap.get("keywords", []),
        "type": cap["type"],
        "endpoint": cap["endpoint"],
        "domain": cap["domain"],
        "environment": cap["environment"],
        "allowed_groups": cap["allowed_groups"],
        "classification": cap["classification"],
        "status": cap["status"],
        "version": cap["version"],
        "owner": cap["owner"],
        "requires_approval": bool(cap["requires_approval"]),
        "payload": json.dumps(cap),
    }


def document_to_record(doc: dict) -> dict:
    return json.loads(doc["payload"])


def create_index_definition(name: str = DEFAULT_INDEX):
    from azure.search.documents.indexes.models import (
        SearchableField,
        SearchFieldDataType,
        SearchIndex,
        SimpleField,
    )

    S = SearchFieldDataType
    fields = [
        SimpleField(name="id", type=S.String, key=True),
        SearchableField(name="name", type=S.String, filterable=True),
        SearchableField(name="description", type=S.String),
        SearchableField(name="keywords", collection=True, type=S.String),
        SearchableField(name="domain", type=S.String, filterable=True),
        SimpleField(name="type", type=S.String, filterable=True),
        SimpleField(name="endpoint", type=S.String),
        SimpleField(name="environment", type=S.String, filterable=True),
        SimpleField(name="allowed_groups", type=S.Collection(S.String), filterable=True),
        SimpleField(name="classification", type=S.String, filterable=True),
        SimpleField(name="status", type=S.String, filterable=True),
        SimpleField(name="version", type=S.String),
        SimpleField(name="owner", type=S.String),
        SimpleField(name="requires_approval", type=S.Boolean, filterable=True),
        SimpleField(name="payload", type=S.String),
    ]
    return SearchIndex(name=name, fields=fields)


class AzureSearchRegistry:
    def __init__(self, search_client=None):
        self._client = search_client

    @property
    def client(self):
        if self._client is None:
            from azure.identity import AzureCliCredential
            from azure.search.documents import SearchClient

            endpoint = os.environ.get("AZURE_SEARCH_ENDPOINT")
            if not endpoint:
                raise RuntimeError("Set AZURE_SEARCH_ENDPOINT (for example https://<name>.search.windows.net).")
            self._client = SearchClient(
                endpoint=endpoint,
                index_name=os.environ.get("AZURE_SEARCH_INDEX", DEFAULT_INDEX),
                credential=AzureCliCredential(),
            )
        return self._client

    def discover(self, query: str, user: User, limit: int = 4) -> DiscoveryResult:
        result = DiscoveryResult()

        # 1) The secure query: the filter runs inside the service.
        allowed_docs = list(
            self.client.search(search_text=query, filter=build_group_filter(user.groups), top=limit, search_mode="any")
        )
        for doc in allowed_docs:
            result.allowed.append(document_to_record(doc))
        allowed_names = {c["name"] for c in result.allowed}

        # 2) Audit only: which matches were held back, and why. Names stay on the server for the
        #    audit log and are never given to the model.
        for doc in self.client.search(
            search_text=query, top=limit, search_mode="any", select=["name", "status", "allowed_groups"]
        ):
            if doc["name"] in allowed_names:
                continue
            reason = (
                f"status is {doc['status']}"
                if doc["status"] != "active"
                else f"user is not in group {list(doc['allowed_groups'])}"
            )
            result.blocked.append((doc["name"], reason))
        return result
