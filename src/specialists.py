"""Specialist agents exposed to a supervisor as tools ('agents as tools').

Use this mode when different business or security domains should be isolated:
each specialist only ever holds the capabilities of its own domain, and the supervisor only
receives the specialists that the signed-in user's groups allow.

Trade-offs to know about (also from the guide):
- Specialists are built once per session, so registry edits are only seen after a restart.
  The default 'single' mode re-reads the registry on every request and is more dynamic.
- To stay safe, specialists here only get capabilities that do NOT need human approval.
  How approval requests travel from an inner agent through as_tool() to the user has not
  been verified for this project. Test it before giving a specialist a high-impact tool.
"""
from __future__ import annotations

from agent_framework import Agent

from .capabilities import resolve_tool
from .registry import User, audit, load_registry

# (tool name, registry domain, group required to use this specialist, description)
SPECIALISTS = [
    ("support_specialist", "IT Support", "Support", "Handles IT incidents and server status questions."),
    ("data_specialist", "Sales", "Data", "Answers sales and revenue questions."),
    ("security_specialist", "Security", "Security", "Handles security alerts and threats."),
    ("knowledge_specialist", "Knowledge", "Everyone", "Finds company documents and policies."),
]


def build_specialist_agents(client, user: User) -> list[tuple[str, Agent]]:
    """One specialist Agent per domain the user may access. Each holds only its own domain's tools."""
    caps = load_registry()
    specialists = []
    for tool_name, domain, group, description in SPECIALISTS:
        if group not in user.groups:
            audit(user, tool_name, "Not exposed", f"user is not in group {group}")
            continue
        tools = [
            resolve_tool(c)
            for c in caps
            if c["domain"] == domain
            and c["type"] == "function"  # MCP capabilities are used through the discovery tool, see README
            and c["status"] == "active"
            and not c["requires_approval"]
            and set(c["allowed_groups"]) & set(user.groups)
        ]
        if not tools:
            continue
        agent = Agent(
            client=client,
            name=tool_name,
            description=description,
            instructions=f"You are the {domain} specialist. Use only your tools. Never invent results.",
            tools=tools,
        )
        audit(user, tool_name, "Exposed", f"{len(tools)} capability(ies)")
        specialists.append((tool_name, agent))
    return specialists


def build_supervisor(client, user: User) -> Agent:
    """A supervisor that delegates to the specialists the user is allowed to reach (agents as tools)."""
    descriptions = {name: desc for name, _d, _g, desc in SPECIALISTS}
    specialist_tools = [
        agent.as_tool(
            name=name,
            description=descriptions[name],
            arg_name="task",
            arg_description="The task to hand to this specialist, in plain words.",
        )
        for name, agent in build_specialist_agents(client, user)
    ]
    return Agent(
        client=client,
        name="Supervisor",
        instructions=(
            "You are a company assistant. Delegate each part of the request to the right specialist tool. "
            "If no specialist fits, say you cannot help. Never invent results."
        ),
        tools=specialist_tools,
    )
