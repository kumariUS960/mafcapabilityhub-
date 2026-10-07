"""Create the Azure AI Search index and upload registry/capabilities.json into it.

Usage (after az login and setting AZURE_SEARCH_ENDPOINT in .env):
    python -m scripts.create_search_index

Your signed-in identity needs, on the search service:
  - 'Search Service Contributor'      (to create the index)
  - 'Search Index Data Contributor'   (to upload documents)
and 'Search Index Data Reader' to query it later.
(The search service must have role-based access control enabled.)
"""
import os

from azure.identity import AzureCliCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from dotenv import load_dotenv

from src.registry import load_registry
from src.search_registry import DEFAULT_INDEX, create_index_definition, record_to_document


def main() -> None:
    load_dotenv()
    endpoint = os.environ["AZURE_SEARCH_ENDPOINT"]
    index_name = os.environ.get("AZURE_SEARCH_INDEX", DEFAULT_INDEX)
    cred = AzureCliCredential()

    SearchIndexClient(endpoint, cred).create_or_update_index(create_index_definition(index_name))
    print(f"Index '{index_name}' is ready.")

    docs = [record_to_document(c) for c in load_registry()]
    results = SearchClient(endpoint, index_name, cred).merge_or_upload_documents(docs)
    ok = sum(1 for r in results if r.succeeded)
    print(f"Uploaded {ok} of {len(docs)} capabilities.")


if __name__ == "__main__":
    main()
