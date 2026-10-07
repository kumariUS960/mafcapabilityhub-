"""Concurrent orchestration: specialists run in parallel (scripted fake model, no Azure)."""
import asyncio
import time

import pytest

pytest.importorskip("agent_framework")

from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message  # noqa: E402

from src.concurrent_brief import run_brief  # noqa: E402
from src.registry import USERS  # noqa: E402


class SlowFake(FunctionInvocationLayer, BaseChatClient):
    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        await asyncio.sleep(0.4)
        return ChatResponse(messages=[Message("assistant", [Content.from_text("status ok")])])


def test_specialists_run_in_parallel_not_one_after_another():
    start = time.perf_counter()
    sections = asyncio.run(run_brief(SlowFake(), USERS["asha"]))
    took = time.perf_counter() - start
    names = [n for n, _ in sections]
    assert sorted(names) == ["knowledge_specialist", "support_specialist"]  # only what Asha's groups allow
    assert took < 0.75  # two 0.4s agents would need 0.8s one after another


def test_user_only_gets_specialists_for_their_groups():
    names = [n for n, _ in asyncio.run(run_brief(SlowFake(), USERS["meera"]))]
    assert sorted(names) == ["knowledge_specialist", "security_specialist"]
