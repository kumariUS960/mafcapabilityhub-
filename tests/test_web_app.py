"""Tests the web API end to end (no browser, no model, no cost)."""
import shutil

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("agent_framework")

from fastapi.testclient import TestClient  # noqa: E402

from src import registry  # noqa: E402
from src.engines import AgentEngine, OfflineEngine  # noqa: E402
from src.web_app import create_app  # noqa: E402
from tests.test_agent_loop import ScriptedClient  # noqa: E402


@pytest.fixture()
def tmp_registry(tmp_path, monkeypatch):
    """Use a private copy of the registry so tests that change a status never touch the real file."""
    target = tmp_path / "capabilities.json"
    shutil.copy(registry.REGISTRY_PATH, target)
    monkeypatch.setattr(registry, "REGISTRY_PATH", target)
    registry.AUDIT.clear()
    return target


def chat(client, user, message, sid="s1"):
    r = client.post("/api/chat", json={"session_id": sid, "user": user, "message": message})
    assert r.status_code == 200, r.text
    return r.json()


def test_page_and_info_are_served(tmp_registry):
    with TestClient(create_app(OfflineEngine())) as client:
        assert "Capability Hub" in client.get("/").text
        info = client.get("/api/info").json()
        assert info["mode"] == "offline"
        assert {"asha", "ravi", "meera", "dev"} <= {u["id"] for u in info["users"]}


def test_offline_allowed_user_gets_function_and_real_mcp_results(tmp_registry):
    with TestClient(create_app(OfflineEngine())) as client:
        data = chat(client, "asha", "latest incident and open helpdesk tickets")
    assert "INC-4821" in data["reply"]
    assert "T-101" in data["reply"]  # a real MCP server answered
    assert any(s["outcome"] == "Succeeded" for s in data["steps"])


def test_offline_blocked_user_sees_no_names_in_the_reply(tmp_registry):
    with TestClient(create_app(OfflineEngine())) as client:
        data = chat(client, "ravi", "latest incident")
    assert "not available to you" in data["reply"]
    assert "get_incidents" not in data["reply"]  # the user is not told which tool exists
    assert any(s["outcome"] == "Blocked" for s in data["steps"])  # but the audit log records it


def test_offline_approval_flow_approve_and_deny(tmp_registry):
    with TestClient(create_app(OfflineEngine())) as client:
        first = chat(client, "asha", "restart the stuck server", sid="a")
        assert [p["name"] for p in first["pending"]] == ["restart_server"]
        done = client.post("/api/approve", json={"session_id": "a", "approval_id": first["pending"][0]["id"], "approved": True}).json()
        assert "Restart of Server A completed" in done["reply"]

        second = chat(client, "asha", "restart the stuck server", sid="b")
        denied = client.post("/api/approve", json={"session_id": "b", "approval_id": second["pending"][0]["id"], "approved": False}).json()
        assert "approval was denied" in denied["reply"]
        assert "Restart of Server A completed" not in denied["reply"]


def test_only_admin_can_change_the_registry_and_it_takes_effect_immediately(tmp_registry):
    with TestClient(create_app(OfflineEngine())) as client:
        refused = client.post("/api/registry/status", json={"user": "asha", "name": "get_incidents", "status": "disabled"})
        assert refused.status_code == 403

        ok = client.post("/api/registry/status", json={"user": "dev", "name": "get_incidents", "status": "disabled"})
        assert ok.status_code == 200
        data = chat(client, "asha", "latest incident")  # no code change, no restart
        assert "get_incidents" not in data["reply"] and "INC-4821" not in data["reply"]

        client.post("/api/registry/status", json={"user": "dev", "name": "get_incidents", "status": "active"})
        assert "INC-4821" in chat(client, "asha", "latest incident")["reply"]


def test_registry_view_marks_what_each_user_can_use(tmp_registry):
    with TestClient(create_app(OfflineEngine())) as client:
        rows = {r["name"]: r for r in client.get("/api/registry", params={"user": "ravi"}).json()}
    assert rows["query_sales_data"]["usable"] is True
    assert rows["get_incidents"]["usable"] is False


def test_unknown_user_and_empty_message_are_rejected(tmp_registry):
    with TestClient(create_app(OfflineEngine())) as client:
        assert client.post("/api/chat", json={"session_id": "x", "user": "nobody", "message": "hi"}).status_code == 404
        assert client.post("/api/chat", json={"session_id": "x", "user": "asha", "message": "  "}).status_code == 400


def test_real_maf_agent_behind_the_same_api_including_approval(tmp_registry):
    script = [
        ("call", "find_capabilities", {"request": "restart the stuck server"}),
        ("call", "restart_server", {"server": "Server A"}),
        ("text", "The server was restarted."),
    ]
    with TestClient(create_app(AgentEngine(ScriptedClient(script)))) as client:
        first = chat(client, "asha", "restart the stuck server")
        assert [p["name"] for p in first["pending"]] == ["restart_server"]  # MAF paused for a human
        done = client.post("/api/approve", json={"session_id": "s1", "approval_id": first["pending"][0]["id"], "approved": True}).json()
    assert done["reply"] == "The server was restarted."
    assert any(s["outcome"] == "Approved" for s in done["steps"])
