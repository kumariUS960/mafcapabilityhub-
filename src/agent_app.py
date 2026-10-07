"""Capability-driven agent built with Microsoft Agent Framework (Python).

Run:   python -m src.agent_app --user asha                    (one agent that discovers capabilities)
       python -m src.agent_app --user meera --mode specialists (supervisor + specialist agents as tools)
       python -m src.agent_app --user asha --mode brief        (specialists run in PARALLEL, one-shot brief)

Model: set MODEL_PROVIDER in .env. 'foundry' (default) needs az login and a Foundry project (billed).
Free options: 'github' (GitHub Models, rate limited) or 'ollama' (local). See README.
Optional: REGISTRY_BACKEND=azure_search (see README), TRACING=console.
Foundry model calls cost money on your Azure subscription; the github and ollama providers do not.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

from agent_framework import Agent, Message
from agent_framework.foundry import FoundryChatClient
from azure.identity import AzureCliCredential

from .backends import backend_name
from .capabilities import close_mcp_connections
from .discovery import make_discovery_tool
from .registry import AUDIT, USERS, User, audit
from .tracing import setup_tracing

SUPERVISOR_INSTRUCTIONS = (
    "You are a company assistant. You start with NO business tools.\n"
    "For any request that needs company data or actions, FIRST call find_capabilities with a short "
    "description of what is needed. Then use only the tools it loaded.\n"
    "If find_capabilities says nothing matches or access is not available, tell the user plainly. "
    "Never invent results. Mention when a tool result is marked [simulated]."
)


def build_client():
    """Pick the model provider with MODEL_PROVIDER in .env: foundry (default), github (free tier), ollama (free, local)."""
    provider = os.environ.get("MODEL_PROVIDER", "foundry").strip().lower()

    if provider == "github":
        # GitHub Models: free, rate-limited, OpenAI-compatible. Needs a token with the models:read permission.
        from agent_framework.openai import OpenAIChatCompletionClient

        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            sys.exit("Set GITHUB_TOKEN in .env (a GitHub token with the Models: Read permission).")
        return OpenAIChatCompletionClient(
            model=os.environ.get("GITHUB_MODEL", "openai/gpt-4.1-mini"),
            api_key=token,
            base_url="https://models.github.ai/inference",
        )

    if provider == "ollama":
        # Ollama: free and fully local. The model you pull must support tool calling.
        from agent_framework.ollama import OllamaChatClient

        return OllamaChatClient(
            host=os.environ.get("OLLAMA_HOST", "http://localhost:11434"),
            model=os.environ.get("OLLAMA_MODEL", "llama3.1"),
        )

    if provider != "foundry":
        sys.exit("MODEL_PROVIDER must be foundry, github or ollama.")

    missing = [v for v in ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL") if not os.environ.get(v)]
    if missing:
        sys.exit(f"Missing {', '.join(missing)}. Copy .env.example to .env and fill it in.")
    return FoundryChatClient(
        project_endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
        model=os.environ["FOUNDRY_MODEL"],
        credential=AzureCliCredential(),
    )


def build_single_agent(client, user: User) -> Agent:
    """One supervisor that discovers capabilities at runtime. Registry is re-read on every request."""
    return Agent(
        client=client,
        name="CapabilitySupervisor",
        instructions=SUPERVISOR_INSTRUCTIONS,
        tools=[make_discovery_tool(user)],  # the agent starts with ONLY the discovery tool
    )


async def run_with_approvals(agent, text: str, session, user: User):
    """Human-in-the-loop: pause for approval on any high-impact tool, then resume the same session."""
    result = await agent.run(text, session=session)
    while result.user_input_requests:
        replies = []
        for request in result.user_input_requests:
            if request.function_call is None:
                continue
            name = request.function_call.name
            print(f"\n  Approval needed for: {name}")
            print(f"  Arguments: {request.function_call.arguments}")
            answer = await asyncio.to_thread(input, "  Approve? (y/n): ")
            approved = answer.strip().lower() == "y"
            audit(user, name, "Approved" if approved else "Denied", "human decision")
            replies.append(Message("user", [request.to_function_approval_response(approved)]))
        result = await agent.run(replies, session=session)
    return result


def print_audit() -> None:
    if not AUDIT:
        print("(audit log is empty)")
        return
    for a in AUDIT:
        print(f"{a['time']}  {a['capability']:<24} {a['outcome']:<12} {a['user']}  {a['detail']}")


async def chat_loop(agent, user: User) -> None:
    session = agent.create_session()
    print("Type a request. Commands: 'audit' shows the log, 'quit' exits.\n")
    while True:
        text = (await asyncio.to_thread(input, "You> ")).strip()
        if text.lower() in {"quit", "exit"}:
            break
        if text.lower() == "audit":
            print_audit()
            continue
        if not text:
            continue
        result = await run_with_approvals(agent, text, session, user)
        print(f"\nAgent> {result.text}\n")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", choices=USERS.keys(), default="asha")
    parser.add_argument("--mode", choices=["single", "specialists", "brief"], default="single")
    args = parser.parse_args()

    load_dotenv()
    tracing = setup_tracing()
    user = USERS[args.user]
    client = build_client()
    print(f"Signed in as {user.name} (groups: {', '.join(user.groups)})")
    print(f"mode: {args.mode} | registry: {backend_name()} | tracing: {tracing}")

    try:
        if args.mode == "brief":
            from .concurrent_brief import run_brief

            sections = await run_brief(client, user)
            if not sections:
                print("No specialists are available for this user.")
            for name, text in sections:
                print(f"\n[{name}]\n{text}")
            print()
            print_audit()
        elif args.mode == "specialists":
            from .specialists import build_supervisor

            await chat_loop(build_supervisor(client, user), user)
        else:
            await chat_loop(build_single_agent(client, user), user)
    finally:
        await close_mcp_connections()


if __name__ == "__main__":
    asyncio.run(main())
