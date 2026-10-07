"""Runs the real agent through the OpenAI-compatible HTTP client (the path GitHub Models uses).

A tiny local server plays the 'model' and speaks the OpenAI chat-completions protocol, so this checks
the real HTTP client, tool-call parsing and the progressive tool exposure over the wire.
No account, no network, no cost. It does NOT prove a real hosted model will choose the right tools.
"""
import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("agent_framework")

from agent_framework import Agent  # noqa: E402
from agent_framework.openai import OpenAIChatCompletionClient  # noqa: E402

from src.discovery import make_discovery_tool  # noqa: E402
from src.registry import USERS  # noqa: E402

REQUESTS: list[dict] = []


def _tool_call(name, args):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"id": f"call_{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}],
    }


class FakeOpenAI(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        REQUESTS.append(body)
        tool_results = sum(1 for m in body["messages"] if m["role"] == "tool")
        if tool_results == 0:
            msg, reason = _tool_call("find_capabilities", {"request": "latest incident"}), "tool_calls"
        elif tool_results == 1:
            msg, reason = _tool_call("get_incidents", {"query": "latest"}), "tool_calls"
        else:
            msg, reason = {"role": "assistant", "content": "Latest incident is INC-4821."}, "stop"
        out = {
            "id": "x", "object": "chat.completion", "created": 0, "model": body.get("model", "m"),
            "choices": [{"index": 0, "message": msg, "finish_reason": reason}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        data = json.dumps(out).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def test_agent_works_through_an_openai_compatible_endpoint():
    REQUESTS.clear()
    server = HTTPServer(("127.0.0.1", 0), FakeOpenAI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = OpenAIChatCompletionClient(
            model="openai/test-model", api_key="not-a-real-key", base_url=f"http://127.0.0.1:{server.server_port}"
        )
        agent = Agent(client=client, name="T", instructions="x", tools=[make_discovery_tool(USERS["asha"])])
        result = asyncio.run(agent.run("latest incident", session=agent.create_session()))
    finally:
        server.shutdown()

    assert "INC-4821" in result.text
    names = [[t["function"]["name"] for t in r.get("tools", [])] for r in REQUESTS]
    assert names[0] == ["find_capabilities"]  # first call to the model: only the discovery tool
    assert "get_incidents" in names[1]  # after discovery, the permitted tool is sent on the next call
