"""The discovery tool: the only tool the supervisor agent starts with.

It uses Agent Framework's progressive tool exposure (the 'loader-tool pattern'):
the agent searches the registry, and only the permitted capabilities are added
to the agent's tool list for the rest of that run. Function AND MCP capabilities are supported.

Note: ctx.add_tools / FunctionInvocationContext is marked experimental in the Microsoft docs,
so names or behavior may change between versions.
"""
from __future__ import annotations

import asyncio
import warnings
from typing import Annotated

from agent_framework import FunctionInvocationContext, tool
from opentelemetry import trace

from .backends import discover_backend
from .capabilities import resolve_tools
from .registry import User, audit

warnings.filterwarnings("ignore", category=FutureWarning)  # hides the 'experimental' notice
tracer = trace.get_tracer("capability_hub")


def make_discovery_tool(user: User):
    """Build a discovery tool bound to one user, so permissions are fixed on the server side.

    The model cannot choose or change which user it acts for.
    """

    @tool(approval_mode="never_require")
    async def find_capabilities(
        request: Annotated[str, "What is needed, in a few words, for example 'latest incidents and server status'"],
        ctx: FunctionInvocationContext,
    ) -> str:
        """Search the company capability registry and load the tools that can help.

        Call this first for any request that needs company data or actions.
        Only tools this user is allowed to use are loaded.
        """
        with tracer.start_as_current_span("capability.discovery") as span:
            span.set_attribute("capability.user", user.id)
            span.set_attribute("capability.request", request)

            # Registry search (may call Azure AI Search, so keep it off the event loop).
            result = await asyncio.to_thread(discover_backend, request, user)

            for name, reason in result.blocked:
                audit(user, name, "Blocked", reason)

            tools, loaded = [], []
            for cap in result.allowed:
                try:
                    tools.extend(await resolve_tools(cap))
                    loaded.append(cap)
                    audit(user, cap["name"], "Loaded", f"v{cap['version']}, type={cap['type']}, approval={cap['requires_approval']}")
                except Exception as exc:  # one broken capability must not break the whole request
                    audit(user, cap["name"], "Load failed", f"{type(exc).__name__}: {exc}")

            span.set_attribute("capability.allowed_count", len(loaded))
            span.set_attribute("capability.blocked_count", len(result.blocked))
            span.set_attribute("capability.loaded", ",".join(c["name"] for c in loaded))

            if not loaded:
                audit(user, "(none)", "No match", f"request: {request}")
                if result.blocked:
                    return (
                        f"{len(result.blocked)} matching capability(ies) exist but are not available to this user. "
                        "Tell the user they do not have access and suggest asking a registry admin."
                    )
                return "No capability in the registry matches this request. Tell the user you cannot help with it."

            ctx.add_tools(tools)  # progressive tool exposure: visible to the model on its next step

            lines = [f"- {c['name']}: {c['description']}" for c in loaded]
            tool_names = ", ".join(t.name for t in tools)
            note = f"\n{len(result.blocked)} other match(es) are not available to this user." if result.blocked else ""
            return f"Loaded these capabilities:\n" + "\n".join(lines) + f"\nTools you can call now: {tool_names}" + note

    return find_capabilities
