"""Concurrent orchestration: several specialist agents work on the same request IN PARALLEL.

Uses Agent Framework's ConcurrentBuilder. Each specialist the user may reach (by group) answers
independently, then the results are collected. Good for a 'daily status brief' across domains.

Remember the guide's warning: do not use several agents just because parallelism is possible.
Use this when the pieces are independent and each area has its own expertise or access rules.
"""
from __future__ import annotations

from agent_framework.orchestrations import ConcurrentBuilder

from .registry import User
from .specialists import build_specialist_agents

BRIEF_PROMPT = "Give a one or two line status update for your area using your tools. Say if a result is simulated."


async def run_brief(client, user: User, prompt: str = BRIEF_PROMPT) -> list[tuple[str, str]]:
    agents = [agent for _name, agent in build_specialist_agents(client, user)]
    if not agents:
        return []
    workflow = ConcurrentBuilder(participants=agents).build()
    events = await workflow.run(prompt)
    sections: list[tuple[str, str]] = []
    for output in events.get_outputs():
        for message in getattr(output, "messages", []):
            if message.role == "assistant":
                sections.append((message.author_name or "agent", message.text))
    return sections
