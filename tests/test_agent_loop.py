"""Tests the real Agent Framework tool loop with a scripted fake 'model'.

No Azure and no model calls are made. The fake model follows a fixed script, which lets us check
what the framework itself does: which tools are visible at each step, and whether approval pauses.
"""
import asyncio
import json
import warnings

import pytest

pytest.importorskip("agent_framework")
warnings.simplefilter("ignore")

from agent_framework import Agent, BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message  # noqa: E402

from src.discovery import make_discovery_tool  # noqa: E402
from src.registry import AUDIT, USERS  # noqa: E402


class ScriptedClient(FunctionInvocationLayer, BaseChatClient):
    def __init__(self, script):
        super().__init__()
        self.script = script
        self.step = 0
        self.tools_seen = []

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        self.tools_seen.append([getattr(t, "name", str(t)) for t in (options.get("tools") or [])])
        action = self.script[self.step]
        self.step += 1
        if action[0] == "call":
            content = Content.from_function_call(call_id=f"c{self.step}", name=action[1], arguments=json.dumps(action[2]))
        else:
            content = Content.from_text(action[1])
        return ChatResponse(messages=[Message("assistant", [content])])


def run(user, script, prompt):
    AUDIT.clear()
    client = ScriptedClient(script)
    agent = Agent(client=client, name="T", instructions="x", tools=[make_discovery_tool(USERS[user])])
    result = asyncio.run(agent.run(prompt, session=agent.create_session()))
    return client, result


def test_agent_starts_with_only_the_discovery_tool_then_gains_permitted_tools():
    client, result = run(
        "asha",
        [("call", "find_capabilities", {"request": "latest incident"}), ("call", "get_incidents", {"query": "latest"}), ("text", "done")],
        "latest incident",
    )
    assert client.tools_seen[0] == ["find_capabilities"]
    assert "get_incidents" in client.tools_seen[1]
    assert result.text == "done"


def test_unauthorized_tool_is_never_exposed_to_the_agent():
    client, _ = run("ravi", [("call", "find_capabilities", {"request": "latest incident"}), ("text", "no access")], "latest incident")
    assert all("get_incidents" not in step for step in client.tools_seen)
    assert ("get_incidents", "Blocked") in [(a["capability"], a["outcome"]) for a in AUDIT]


def test_high_impact_tool_pauses_for_human_approval():
    _, result = run(
        "asha",
        [("call", "find_capabilities", {"request": "restart the stuck server"}), ("call", "restart_server", {"server": "Server A"}), ("text", "restarted")],
        "restart",
    )
    assert [r.function_call.name for r in result.user_input_requests] == ["restart_server"]
