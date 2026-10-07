"""The actual capability implementations (the 'kitchen') and the Capability Resolution Layer.

Two kinds of capability are supported:

* type "function": a plain Python function in this file (simulated result). The resolution layer
  wraps it as an Agent Framework tool. Approval comes from the registry, not from the code.
* type "mcp": a real MCP server described in the registry entry (command, args, allowed_tools).
  The resolution layer connects to it with MAF's MCPStdioTool and exposes only the
  tools listed in allowed_tools (least privilege).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated, Callable

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_incidents(query: Annotated[str, "What to look for, e.g. 'latest' or 'Server A'"] = "latest") -> str:
    """Search incident tickets by date and filter."""
    return f"Incident INC-4821 (Server A, high priority, opened 2 hours ago) matched '{query}'. [simulated]"


def get_server_status(server: Annotated[str, "Server name, e.g. 'Server A'"] = "Server A") -> str:
    """Check the health, status and uptime of a server."""
    return f"{server} is up. CPU 72%. Last restart 9 days ago. [simulated]"


def restart_server(server: Annotated[str, "Name of the server to restart, e.g. 'Server A'"]) -> str:
    """Restart a server. High impact: needs human approval."""
    return f"Restart of {server} completed. [simulated]"


def search_documents(query: Annotated[str, "What document to look for"]) -> str:
    """Search company documents, policies and handbooks."""
    return f"Found 'Leave Policy v4' for '{query}', updated this quarter. [simulated]"


def query_sales_data(period: Annotated[str, "Time period, e.g. 'this quarter'"] = "this quarter") -> str:
    """Query sales revenue numbers for a period."""
    return f"Revenue {period} is up 8% compared with the previous period. [simulated]"


def check_security_alerts(severity: Annotated[str, "Minimum severity, e.g. 'medium'"] = "medium") -> str:
    """Check current security alerts at or above a severity."""
    return f"2 medium alerts and 0 critical alerts at or above '{severity}'. [simulated]"


IMPLEMENTATIONS: dict[str, Callable[..., str]] = {
    f.__name__: f
    for f in (get_incidents, get_server_status, restart_server, search_documents, query_sales_data, check_security_alerts)
}

# Cache so the same tool object is reused. Agent Framework rejects two different tool objects
# with the same name in one run.
_TOOL_CACHE: dict[tuple[str, bool], object] = {}
_MCP_CACHE: dict[str, object] = {}  # capability id -> connected MCPStdioTool


def resolve_tool(cap: dict):
    """Resolve a FUNCTION capability into an executable Agent Framework tool.

    The approval requirement comes from the registry entry, not from the code.
    """
    from agent_framework import tool  # imported here so offline tools and tests do not need the framework

    name = cap["name"]
    if name not in IMPLEMENTATIONS:
        raise KeyError(f"No implementation registered for capability '{name}'")
    needs_approval = bool(cap.get("requires_approval", False))
    key = (name, needs_approval)
    if key not in _TOOL_CACHE:
        mode = "always_require" if needs_approval else "never_require"
        _TOOL_CACHE[key] = tool(approval_mode=mode)(IMPLEMENTATIONS[name])
    return _TOOL_CACHE[key]


async def connect_mcp(cap: dict):
    """Connect (once) to the MCP server described by a registry entry and return the connected tool."""
    from agent_framework import MCPStdioTool

    cid = cap["id"]
    if cid in _MCP_CACHE:
        return _MCP_CACHE[cid]

    cfg = cap.get("mcp") or {}
    if cfg.get("transport", "stdio") != "stdio":
        raise NotImplementedError("This project implements the stdio transport only. See README for HTTP.")

    command = sys.executable if cfg.get("command") == "python" else cfg["command"]
    args = [str(PROJECT_ROOT / a) if a.endswith(".py") and not Path(a).is_absolute() else a for a in cfg.get("args", [])]
    mcp_tool = MCPStdioTool(
        name=cap["name"],
        command=command,
        args=args,
        allowed_tools=cfg.get("allowed_tools"),  # least privilege: hide every other tool on the server
        approval_mode="always_require" if cap.get("requires_approval") else "never_require",
    )
    await mcp_tool.connect()
    _MCP_CACHE[cid] = mcp_tool
    return mcp_tool


async def resolve_tools(cap: dict) -> list:
    """Capability Resolution Layer: registry entry -> list of executable tools (function or MCP)."""
    if cap.get("type") == "mcp":
        mcp_tool = await connect_mcp(cap)
        return list(mcp_tool.functions)
    return [resolve_tool(cap)]


async def close_mcp_connections() -> None:
    for mcp_tool in list(_MCP_CACHE.values()):
        await mcp_tool.close()
    _MCP_CACHE.clear()
