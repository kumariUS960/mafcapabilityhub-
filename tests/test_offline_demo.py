"""Regression test: every FUNCTION capability must run in the offline demo with the arguments in the registry.

This catches the case where a capability needs an argument (for example restart_server needs a server name)
but the demo called it with none, which only shows up after a human approves the action.
"""
import asyncio

from src.capabilities import IMPLEMENTATIONS
from src.offline_demo import run_one
from src.registry import load_registry


def test_every_function_capability_runs_offline_with_registry_arguments():
    for cap in load_registry():
        if cap["type"] != "function":
            continue
        assert cap["name"] in IMPLEMENTATIONS
        cap = dict(cap, simulated_latency_ms=1)  # keep the test fast
        out = asyncio.run(run_one(cap))
        assert isinstance(out, str) and out


def test_restart_server_runs_after_approval_path():
    cap = next(c for c in load_registry() if c["name"] == "restart_server")
    assert cap["requires_approval"] is True
    out = asyncio.run(run_one(dict(cap, simulated_latency_ms=1)))
    assert "Restart of Server A completed" in out
