"""Tracing with OpenTelemetry through Agent Framework's built-in instrumentation.

TRACING=console     print spans and metrics in the terminal (good for learning and demos)
TRACING=otlp        send to an OTLP endpoint (set OTEL_EXPORTER_OTLP_ENDPOINT)
(unset)             tracing off

Agent Framework then records agent runs, model calls and tool calls. This project also adds its own
'capability.discovery' span, so you can see request -> discovery -> selection -> tool call in one trace.

For Azure Application Insights, use the Azure Monitor OpenTelemetry package and set up the
exporter before running the agent (see Microsoft Learn: Agent Framework observability).
"""
from __future__ import annotations

import os


def setup_tracing() -> str:
    mode = os.environ.get("TRACING", "").strip().lower()
    if mode not in {"console", "otlp"}:
        return "off"
    from agent_framework.observability import configure_otel_providers

    if mode == "console":
        configure_otel_providers(enable_console_exporters=True)
    else:
        configure_otel_providers()
    return mode
