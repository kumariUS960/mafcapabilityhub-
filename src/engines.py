"""Two interchangeable engines behind the web app.

OfflineEngine  No model, no cost. Keyword search stands in for the model's decision, but it uses the
               SAME registry, permission filter, approval rule, MCP connection and audit log.
AgentEngine    The real Microsoft Agent Framework agent (model from MODEL_PROVIDER: github, ollama, foundry).

Both return the same TurnResult, so the web page does not care which one is running.
Choose with MODEL_PROVIDER in .env. If it is unset or 'offline', the offline engine is used.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field

from .offline_demo import run_one
from .registry import AUDIT, User, audit, discover


@dataclass
class TurnResult:
    reply: str = ""
    pending: list[dict] = field(default_factory=list)  # approvals waiting for a human: {id, name, arguments}
    steps: list[dict] = field(default_factory=list)  # audit entries created during this turn


def _since(start: int) -> list[dict]:
    return [dict(a) for a in AUDIT[start:]]


class OfflineEngine:
    mode = "offline"

    def __init__(self) -> None:
        self.sessions: dict[str, dict] = {}

    async def chat(self, sid: str, user: User, text: str) -> TurnResult:
        start = len(AUDIT)
        result = discover(text, user)
        for name, reason in result.blocked:
            audit(user, name, "Blocked", reason)

        if not result.allowed:
            audit(user, "(none)", "No match", f"request: {text}")
            if result.blocked:
                reply = (
                    f"{len(result.blocked)} matching capability(ies) exist but are not available to you. "
                    "Ask a registry admin if you should have access."
                )
            else:
                reply = "I could not find a capability in the registry that matches that request."
            return TurnResult(reply=reply, steps=_since(start))

        for cap in result.allowed:
            audit(user, cap["name"], "Loaded", f"v{cap['version']}, type={cap['type']}, approval={cap['requires_approval']}")

        approvals = {uuid.uuid4().hex[:8]: cap for cap in result.allowed if cap["requires_approval"]}
        state = {"user": user, "caps": result.allowed, "approvals": approvals, "decisions": {}}
        self.sessions[sid] = state

        if approvals:
            pending = [
                {"id": i, "name": c["name"], "arguments": c.get("offline_call", {}).get("args", {})}
                for i, c in approvals.items()
            ]
            return TurnResult(reply="I need your approval before running a high-impact action.", pending=pending, steps=_since(start))
        return await self._run(state, start)

    async def decide(self, sid: str, approval_id: str, approved: bool) -> TurnResult:
        start = len(AUDIT)
        state = self.sessions.get(sid)
        if not state or approval_id not in state["approvals"]:
            return TurnResult(reply="That approval is no longer pending.")
        cap = state["approvals"][approval_id]
        state["decisions"][approval_id] = approved
        audit(state["user"], cap["name"], "Approved" if approved else "Denied", "human decision")

        if len(state["decisions"]) < len(state["approvals"]):
            remaining = [
                {"id": i, "name": c["name"], "arguments": c.get("offline_call", {}).get("args", {})}
                for i, c in state["approvals"].items()
                if i not in state["decisions"]
            ]
            return TurnResult(reply="Waiting for the remaining approvals.", pending=remaining, steps=_since(start))
        return await self._run(state, start)

    async def _run(self, state: dict, start: int) -> TurnResult:
        user = state["user"]
        approved_names = {
            c["name"] for i, c in state["approvals"].items() if state["decisions"].get(i)
        }
        to_run = [c for c in state["caps"] if not c["requires_approval"] or c["name"] in approved_names]
        denied = [c["name"] for c in state["caps"] if c["requires_approval"] and c["name"] not in approved_names]

        outputs = await asyncio.gather(*(run_one(c) for c in to_run), return_exceptions=True)
        lines = []
        for cap, out in zip(to_run, outputs):
            if isinstance(out, Exception):
                audit(user, cap["name"], "Failed", f"{type(out).__name__}: {out}")
                lines.append(f"- {cap['name']} failed.")
            else:
                audit(user, cap["name"], "Succeeded", "")
                lines.append(f"- {cap['name']}: {out}")
        for name in denied:
            lines.append(f"- {name} was not run because approval was denied.")
        reply = "Here is what I found:\n" + "\n".join(lines) if lines else "Nothing was run."
        return TurnResult(reply=reply, steps=_since(start))


class AgentEngine:
    """The real MAF agent. The model decides which capabilities to ask for."""

    def __init__(self, client) -> None:
        self.client = client
        self.mode = os.environ.get("MODEL_PROVIDER", "model").lower()
        self.sessions: dict[str, dict] = {}

    def _state(self, sid: str, user: User) -> dict:
        from .agent_app import build_single_agent

        state = self.sessions.get(sid)
        if state is None or state["user"].id != user.id:
            agent = build_single_agent(self.client, user)
            state = {"user": user, "agent": agent, "session": agent.create_session(), "pending": {}, "decisions": {}}
            self.sessions[sid] = state
        return state

    async def chat(self, sid: str, user: User, text: str) -> TurnResult:
        start = len(AUDIT)
        state = self._state(sid, user)
        result = await state["agent"].run(text, session=state["session"])
        return self._pack(state, result, start)

    async def decide(self, sid: str, approval_id: str, approved: bool) -> TurnResult:
        from agent_framework import Message

        start = len(AUDIT)
        state = self.sessions.get(sid)
        if not state or approval_id not in state["pending"]:
            return TurnResult(reply="That approval is no longer pending.")
        req = state["pending"][approval_id]
        state["decisions"][approval_id] = approved
        audit(state["user"], req.function_call.name, "Approved" if approved else "Denied", "human decision")

        if len(state["decisions"]) < len(state["pending"]):
            remaining = [self._describe(i, r) for i, r in state["pending"].items() if i not in state["decisions"]]
            return TurnResult(reply="Waiting for the remaining approvals.", pending=remaining, steps=_since(start))

        replies = [Message("user", [state["pending"][i].to_function_approval_response(d)]) for i, d in state["decisions"].items()]
        state["pending"], state["decisions"] = {}, {}
        result = await state["agent"].run(replies, session=state["session"])
        return self._pack(state, result, start)

    @staticmethod
    def _describe(approval_id: str, request) -> dict:
        return {"id": approval_id, "name": request.function_call.name, "arguments": str(request.function_call.arguments)}

    def _pack(self, state: dict, result, start: int) -> TurnResult:
        if result.user_input_requests:
            state["pending"] = {uuid.uuid4().hex[:8]: r for r in result.user_input_requests if r.function_call is not None}
            state["decisions"] = {}
            pending = [self._describe(i, r) for i, r in state["pending"].items()]
            return TurnResult(reply=result.text or "I need your approval before running a high-impact action.", pending=pending, steps=_since(start))
        return TurnResult(reply=result.text or "(no answer)", steps=_since(start))


def create_engine():
    provider = os.environ.get("MODEL_PROVIDER", "offline").strip().lower()
    if provider in ("", "offline"):
        return OfflineEngine()
    from .agent_app import build_client

    return AgentEngine(build_client())
