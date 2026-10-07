"""The project's own 'capability.discovery' span is emitted with useful attributes."""
import asyncio

import pytest

pytest.importorskip("agent_framework")
pytest.importorskip("opentelemetry.sdk")

from opentelemetry import trace  # noqa: E402
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter  # noqa: E402

from agent_framework import Agent  # noqa: E402

from src.discovery import make_discovery_tool  # noqa: E402
from src.registry import USERS  # noqa: E402
from tests.test_agent_loop import ScriptedClient  # noqa: E402


def test_discovery_span_records_user_request_and_outcome():
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    import src.discovery as d

    d.tracer = provider.get_tracer("capability_hub")  # use the test provider

    client = ScriptedClient([("call", "find_capabilities", {"request": "latest incident"}), ("text", "done")])
    agent = Agent(client=client, name="T", instructions="x", tools=[make_discovery_tool(USERS["asha"])])
    asyncio.run(agent.run("latest incident", session=agent.create_session()))

    spans = [s for s in exporter.get_finished_spans() if s.name == "capability.discovery"]
    assert len(spans) == 1
    attrs = spans[0].attributes
    assert attrs["capability.user"] == "asha"
    assert attrs["capability.allowed_count"] >= 1
    assert "get_incidents" in attrs["capability.loaded"]
