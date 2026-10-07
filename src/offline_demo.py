"""Offline demo. No Azure, no model, no cost.

It runs the SAME registry, permission filter and capability code as the real agent, but
replaces the AI model's decision with simple keyword matching. MCP capabilities really start
their local MCP server, so you can see the allowed_tools (least privilege) filter working.
Use it to check your registry and permissions before spending any model calls.

Run:  python -m src.offline_demo --user asha "latest incident and open tickets"
"""
from __future__ import annotations

import argparse
import asyncio
import time

from .capabilities import IMPLEMENTATIONS, close_mcp_connections, connect_mcp
from .registry import AUDIT, USERS, audit, discover


async def run_one(cap: dict) -> str:
    if cap["type"] == "mcp":
        mcp_tool = await connect_mcp(cap)
        names = [f.name for f in mcp_tool.functions]
        call = cap.get("offline_call", {})
        fn = next((f for f in mcp_tool.functions if f.name == call.get("tool")), None)
        out = "(no offline_call set)"
        if fn is not None:
            result = await fn.invoke(**call.get("args", {}))
            out = " ".join(getattr(c, "text", "") or str(c) for c in result).strip()
        return f"MCP tools exposed: {names}. {call.get('tool')} -> {out}"
    await asyncio.sleep(cap.get("simulated_latency_ms", 300) / 1000)  # pretend the call takes time
    return IMPLEMENTATIONS[cap["name"]](**cap.get("offline_call", {}).get("args", {}))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("request")
    parser.add_argument("--user", choices=USERS.keys(), default="asha")
    args = parser.parse_args()

    user = USERS[args.user]
    print(f"User: {user.name}  groups: {', '.join(user.groups)}")
    print(f"Request: {args.request}\n")

    result = discover(args.request, user)
    for name, reason in result.blocked:
        audit(user, name, "Blocked", reason)
        print(f"  BLOCKED  {name}: {reason}")

    to_run = []
    for cap in result.allowed:
        if cap["requires_approval"]:
            answer = input(f"  {cap['name']} is high impact. Approve? (y/n): ").strip().lower()
            if answer != "y":
                audit(user, cap["name"], "Denied", "human decision")
                print(f"  DENIED   {cap['name']}")
                continue
            audit(user, cap["name"], "Approved", "human decision")
        to_run.append(cap)

    try:
        if not to_run:
            print("\nNothing to run for this user.")
            return

        print(f"\nRunning {len(to_run)} capability(ies) in parallel...")
        start = time.perf_counter()
        outputs = await asyncio.gather(*(run_one(c) for c in to_run))
        took = (time.perf_counter() - start) * 1000
        sequential = sum(c.get("simulated_latency_ms", 300) for c in to_run)
        for cap, out in zip(to_run, outputs):
            audit(user, cap["name"], "Succeeded", "")
            print(f"  OK       {cap['name']} [{cap['type']}]: {out}")
        print(f"\nParallel: about {took:.0f} ms (simulated one-after-another: about {sequential} ms).")
    finally:
        await close_mcp_connections()
        print("\nAudit log:")
        for a in AUDIT:
            print(f"  {a['time']}  {a['capability']:<24} {a['outcome']:<10} {a['detail']}")


if __name__ == "__main__":
    asyncio.run(main())
