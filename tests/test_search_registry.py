"""Azure AI Search backend: filter building and record mapping, using a fake client (no Azure)."""
from src.registry import USERS, load_registry
from src.search_registry import AzureSearchRegistry, build_group_filter, document_to_record, record_to_document


def test_filter_is_security_trimmed_by_group_and_status():
    f = build_group_filter(("Support", "Everyone"))
    assert f == "status eq 'active' and allowed_groups/any(g: search.in(g, 'Support,Everyone', ','))"


def test_filter_escapes_quotes_and_handles_no_groups():
    assert "O''Brien" in build_group_filter(("O'Brien",))
    assert build_group_filter(()).endswith("false")


def test_record_round_trips_through_a_search_document():
    cap = next(c for c in load_registry() if c["name"] == "ticket_system")
    doc = record_to_document(cap)
    assert doc["allowed_groups"] == ["Support"] and doc["status"] == "active"
    assert document_to_record(doc) == cap  # the resolution layer gets the same dict as with the local registry


class FakeSearchClient:
    """Pretends to be Azure AI Search: applies a very small version of the real behavior."""

    def __init__(self, caps):
        self.docs = [record_to_document(c) for c in caps]
        self.calls = []

    def search(self, search_text, filter=None, top=4, search_mode="any", select=None):
        self.calls.append({"filter": filter, "select": select})
        words = set(search_text.lower().split())
        hits = [d for d in self.docs if words & set((d["name"].replace("_", " ") + " " + d["description"]).lower().split())]
        if filter:  # emulate: active + group overlap
            groups = filter.split("search.in(g, '")[1].split("'")[0].split(",")
            hits = [d for d in hits if d["status"] == "active" and set(d["allowed_groups"]) & set(groups)]
        return hits[:top]


def test_azure_backend_sends_the_group_filter_and_records_blocked_matches():
    client = FakeSearchClient(load_registry())
    reg = AzureSearchRegistry(search_client=client)
    result = reg.discover("security alerts", USERS["asha"])
    assert result.allowed == []  # the secure query returned nothing for Asha
    assert any(n == "check_security_alerts" for n, _ in result.blocked)  # but the audit knows it was held back
    assert "allowed_groups/any" in client.calls[0]["filter"]
    assert client.calls[1]["filter"] is None and client.calls[1]["select"]  # audit-only query, minimal fields


def test_azure_backend_returns_permitted_capability_for_the_right_user():
    reg = AzureSearchRegistry(search_client=FakeSearchClient(load_registry()))
    result = reg.discover("security alerts", USERS["meera"])
    assert [c["name"] for c in result.allowed] == ["check_security_alerts"]
