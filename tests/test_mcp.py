"""Tests a REAL local MCP server connected through Agent Framework's MCPStdioTool."""
import asyncio
import json

import pytest

pytest.importorskip("agent_framework")

from agent_framework import Agent  # noqa: E402

from src.capabilities import close_mcp_connections, resolve_tools  # noqa: E402
from src.discovery import make_discovery_tool  # noqa: E402
from src.registry import AUDIT, USERS, load_registry  # noqa: E402
from tests.test_agent_loop import ScriptedClient  # noqa: E402


def ticket_cap():
    return next(c for c in load_registry() if c["name"] == "ticket_system")


def test_only_allowed_mcp_tools_are_exposed_least_privilege():
    async def go():
        try:
            tools = await resolve_tools(ticket_cap())
            return sorted(t.name for t in tools)
        finally:
            await close_mcp_connections()

    names = asyncio.run(go())
    assert names == ["get_ticket", "list_tickets"]
    assert "delete_ticket" not in names  # exists on the server, hidden from the agent


def test_agent_discovers_and_calls_an_mcp_tool_through_the_registry():
    async def go():
        AUDIT.clear()
        client = ScriptedClient(
            [
                ("call", "find_capabilities", {"request": "open helpdesk tickets"}),
                ("call", "list_tickets", {"status": "open"}),
                ("text", "done"),
            ]
        )
        agent = Agent(client=client, name="T", instructions="x", tools=[make_discovery_tool(USERS["asha"])])
        try:
            result = await agent.run("open tickets", session=agent.create_session())
        finally:
            await close_mcp_connections()
        return client, result

    client, result = asyncio.run(go())
    assert client.tools_seen[0] == ["find_capabilities"]
    assert "list_tickets" in client.tools_seen[1] and "get_ticket" in client.tools_seen[1]
    assert all("delete_ticket" not in step for step in client.tools_seen)
    # The tool result that went back to the model contains real data from the MCP server.
    results = [c.result for m in result.messages for c in m.contents if c.type == "function_result"]
    assert "T-101" in json.dumps([str(r) for r in results])


def test_mcp_capability_is_not_exposed_to_a_user_outside_the_group():
    async def go():
        AUDIT.clear()
        client = ScriptedClient([("call", "find_capabilities", {"request": "open helpdesk tickets"}), ("text", "no access")])
        agent = Agent(client=client, name="T", instructions="x", tools=[make_discovery_tool(USERS["ravi"])])
        try:
            await agent.run("open tickets", session=agent.create_session())
        finally:
            await close_mcp_connections()
        return client

    client = asyncio.run(go())
    assert all("list_tickets" not in step for step in client.tools_seen)
