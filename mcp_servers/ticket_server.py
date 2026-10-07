"""A small REAL MCP server (stdio) that stands in for a ticket system.

It exposes three tools. The registry only allows the two safe ones through
(`allowed_tools`), which demonstrates least-privilege tool filtering:
`delete_ticket` exists on the server but the agent can never see or call it.

Run standalone to check it starts:  python mcp_servers/ticket_server.py   (it waits for an MCP client)
"""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("ticket-system")

TICKETS = {
    "T-101": {"title": "VPN drops every hour", "status": "open", "priority": "high"},
    "T-102": {"title": "Printer offline on floor 2", "status": "open", "priority": "low"},
    "T-103": {"title": "Email sync delay", "status": "closed", "priority": "medium"},
}


@mcp.tool()
def list_tickets(status: str = "open") -> str:
    """List support tickets with the given status ('open' or 'closed')."""
    rows = [f"{tid}: {t['title']} ({t['priority']})" for tid, t in TICKETS.items() if t["status"] == status]
    return "\n".join(rows) or f"No {status} tickets."


@mcp.tool()
def get_ticket(ticket_id: str) -> str:
    """Get the details of one ticket, for example 'T-101'."""
    t = TICKETS.get(ticket_id)
    return f"{ticket_id}: {t['title']} | status={t['status']} | priority={t['priority']}" if t else "Ticket not found."


@mcp.tool()
def delete_ticket(ticket_id: str) -> str:
    """Delete a ticket permanently. DANGEROUS: the registry does not allow the agent to use this."""
    TICKETS.pop(ticket_id, None)
    return f"{ticket_id} deleted."


if __name__ == "__main__":
    mcp.run(transport="stdio")
