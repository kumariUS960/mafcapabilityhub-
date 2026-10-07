# Capability-Driven Agent with Microsoft Agent Framework (MAF)

A working agent built on Microsoft Agent Framework (Python) that follows the
"MAF + Microsoft Foundry Dynamic Agent Architecture" guide. The agent does NOT start with a fixed
list of tools. It searches a capability registry, gets only the tools the signed-in user may use
(functions and MCP servers), and runs them. High-impact actions wait for human approval.

Built and tested with agent-framework 1.20.0, Python 3.12. **25 tests pass.**

## What is in it

| Guide idea | Where it is | How it was checked |
|---|---|---|
| Capability Registry, metadata contract | `registry/capabilities.json`, `src/registry.py` | unit tests |
| Registry in Azure AI Search, security trimming | `src/search_registry.py`, `scripts/create_search_index.py` | filter and mapping unit tested with a fake client. **Not run against a real service** |
| Runtime discovery + authorization before exposure | `src/discovery.py` (MAF progressive tool exposure) | tests with the real MAF tool loop and a scripted model |
| Resolution layer (function and MCP) | `src/capabilities.py` | tests |
| **Real MCP server** + least-privilege `allowed_tools` | `mcp_servers/ticket_server.py`, `MCPStdioTool` | tests: real stdio server, `delete_ticket` is hidden |
| Human approval for high-impact actions | `requires_approval` in the registry becomes `approval_mode="always_require"` | test |
| Specialist agents (agents as tools) | `src/specialists.py` | smoke tested, plus parallel test |
| **Concurrent orchestration** (parallel agents) | `src/concurrent_brief.py` (`ConcurrentBuilder`) | test: two 0.4 s agents finish in under 0.75 s |
| **Tracing** (OpenTelemetry) | `src/tracing.py`, custom `capability.discovery` span | console output checked, span test |
| Validation before a capability goes live | `validate_capability()` | unit tests |
| Audit log | `AUDIT` in `src/registry.py` | tests |

## Commands

| Command | Azure/model needed? | What it does |
|---|---|---|
| `python -m pytest -q` | No | Runs all 25 tests |
| `python -m src.offline_demo --user asha "latest incident and open tickets"` | No | Registry + permissions + approval + a real MCP call, no model |
| `python -m src.agent_app --user asha` | Yes | The real agent. A Foundry model decides what to ask for |
| `python -m src.agent_app --user meera --mode specialists` | Yes | Supervisor with specialist agents as tools |
| `python -m src.agent_app --user asha --mode brief` | Yes | Specialists run in parallel for a status brief |
| `TRACING=console` before any command | | Prints traces and metrics |

## Setup (Windows PowerShell, from this folder)

```
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q
python -m src.offline_demo --user asha "latest incident and open tickets"
```

If PowerShell blocks the activate script: `Set-ExecutionPolicy -Scope Process Bypass`, then try again.

## Run the real agent

1. `az login`
2. Copy `.env.example` to `.env`; fill `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` from your Foundry project.
3. `python -m src.agent_app --user asha`, then try:
   - "Find the latest incident and open tickets"
   - "Restart the stuck server" (asks you to approve)
   - "Any security alerts?" (blocked for Asha, allowed with `--user meera`)
   - Type `audit` for the log, `quit` to exit.

**Cost warning:** each request calls a model on Azure, billed per use. Ask your lead which Foundry project and model to use. The offline demo and tests cost nothing.

## Use Azure AI Search as the registry

1. Create an Azure AI Search service with role-based access enabled.
2. Give your signed-in identity: Search Service Contributor, Search Index Data Contributor, Search Index Data Reader.
3. In `.env` set `REGISTRY_BACKEND=azure_search` and `AZURE_SEARCH_ENDPOINT`.
4. Run `python -m scripts.create_search_index` once to create the index and upload the registry.
5. Run the agent as before. Discovery now queries the index, with the permission filter applied inside the service.

Search service pricing varies by tier; check the price before creating one.

## Try the "dynamic" part

While the agent is running, edit `registry/capabilities.json`: set a capability's `"status"` to `"disabled"`,
or add a new entry (function capabilities need a Python function in `src/capabilities.py`; MCP capabilities only
need the `mcp` block). The registry is re-read on every request, so the next question sees the change.
No code change and no redeploy.

## Honest limits

- **Not verified here:** real Foundry model calls (`agent_app.py`), a real Azure AI Search service, Application Insights,
  and HTTP MCP servers. Everything else listed above was run. Expect small first-run fixes.
- Function capabilities return **simulated** results. The MCP ticket server is real but a stand-in with fake data.
- Users are a dictionary (`asha`, `ravi`, `meera`); real groups would come from Microsoft Entra ID.
- Search is keyword based. Words like "server" can match more than one capability, which is one reason approval exists.
- Progressive tool exposure is marked **experimental** by Microsoft and may change.
- Specialist agents only get function capabilities without approval, because approval through `as_tool()` was not verified.
  Specialists are built once per session, so registry edits there need a restart.
- Only the stdio MCP transport is wired into the registry. HTTP (`MCPStreamableHTTPTool`) would be a small addition.
- Not covered: Foundry Toolboxes, Magentic orchestration, durable checkpoints, evaluation of selection accuracy.

## Layout

```
registry/capabilities.json   the catalog (metadata contract), 7 capabilities incl. one MCP
mcp_servers/ticket_server.py a real MCP server (3 tools; the registry allows 2)
src/registry.py              search, permission filter, validation, audit (no MAF dependency)
src/search_registry.py       Azure AI Search backend
src/backends.py              local JSON or Azure AI Search
src/capabilities.py          function capabilities and the resolution layer (function + MCP)
src/discovery.py             find_capabilities tool (progressive tool exposure, tracing span)
src/specialists.py           specialist agents, supervisor with agents as tools
src/concurrent_brief.py      parallel specialists with ConcurrentBuilder
src/tracing.py               OpenTelemetry setup
src/agent_app.py             the MAF agent and CLI
src/offline_demo.py          no-cost demo
scripts/create_search_index.py   create and fill the Azure AI Search index
tests/                       25 tests
```
