"""Capability registry: the catalog of what exists, who may use it, and whether it is active.

This file has NO dependency on Microsoft Agent Framework, so it can be tested on its own.
It stands in for Azure AI Search. In the real design, load_registry() and score() would be
replaced by a query to an Azure AI Search index that applies the same security filter.

The registry is re-read from disk on every discovery call. Edit registry/capabilities.json
while the app is running (for example set a status to "disabled") and the next request sees it.
No code change and no redeploy is needed.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "registry" / "capabilities.json"

VALID_STATUSES = {"active", "disabled", "deprecated", "pending"}

STOPWORDS = {
    "the", "and", "a", "an", "of", "to", "for", "any", "show", "find", "check", "me", "is",
    "in", "on", "that", "this", "are", "what", "please", "can", "you", "my", "i", "do",
}


@dataclass(frozen=True)
class User:
    id: str
    name: str
    groups: tuple[str, ...]
    admin: bool = False  # registry admins may change a capability's status from the web app


# Demo users. In a real system these come from Microsoft Entra ID groups, not a dictionary.
USERS: dict[str, User] = {
    "asha": User("asha", "Asha (Support Engineer)", ("Support", "Everyone")),
    "ravi": User("ravi", "Ravi (Data Analyst)", ("Data", "Everyone")),
    "meera": User("meera", "Meera (Security Analyst)", ("Security", "Everyone")),
    "dev": User("dev", "Dev (Registry Admin)", ("Everyone",), admin=True),
}


@dataclass
class DiscoveryResult:
    allowed: list[dict] = field(default_factory=list)
    blocked: list[tuple[str, str]] = field(default_factory=list)  # (capability name, reason)


AUDIT: list[dict] = []


def audit(user: User, capability: str, outcome: str, detail: str = "") -> None:
    AUDIT.append(
        {
            "time": datetime.now().strftime("%H:%M:%S"),
            "user": user.name,
            "capability": capability,
            "outcome": outcome,
            "detail": detail,
        }
    )


def load_registry(path: Path | None = None) -> list[dict]:
    with open(path or REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


def set_status(name: str, status: str, path: Path | None = None) -> None:
    """Change a capability's status in the registry file (active, disabled or deprecated).

    This is how an admin turns a capability off without touching agent code. The next request sees it.
    """
    if status not in {"active", "disabled", "deprecated"}:
        raise ValueError("status must be active, disabled or deprecated")
    target = path or REGISTRY_PATH
    caps = load_registry(target)
    for cap in caps:
        if cap["name"] == name:
            cap["status"] = status
            break
    else:
        raise KeyError(name)
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(caps, indent=2), encoding="utf-8")
    tmp.replace(target)


def _tokens(text: str) -> list[str]:
    words = [w for w in re.split(r"[^a-z0-9]+", text.lower()) if w and w not in STOPWORDS]
    # Very light stemming so "incidents" matches "incident".
    return [w[:-1] if len(w) > 3 and w.endswith("s") else w for w in words]


def score(query: str, cap: dict) -> int:
    haystack = " ".join(
        [cap["name"].replace("_", " "), cap["description"], cap.get("domain", ""), " ".join(cap.get("keywords", []))]
    ).lower()
    haystack_words = set(_tokens(haystack))
    return sum(1 for t in set(_tokens(query)) if t in haystack_words)


def discover(query: str, user: User, caps: list[dict] | None = None, limit: int = 4) -> DiscoveryResult:
    """Search the registry, then drop anything the user may not use.

    Order matters: search first, then filter by status and by group, BEFORE anything
    is exposed to the agent. The agent cannot misuse a tool it never sees.
    """
    caps = caps if caps is not None else load_registry()
    matches = sorted(((score(query, c), c) for c in caps), key=lambda x: -x[0])
    result = DiscoveryResult()
    for s, cap in matches:
        if s <= 0 or len(result.allowed) + len(result.blocked) >= limit:
            continue
        if cap["status"] != "active":
            result.blocked.append((cap["name"], f"status is {cap['status']}"))
        elif not set(cap["allowed_groups"]) & set(user.groups):
            result.blocked.append((cap["name"], f"user is not in group {cap['allowed_groups']}"))
        else:
            result.allowed.append(cap)
    return result


def validate_capability(cap: dict) -> list[str]:
    """Checks a new capability must pass before it can become active."""
    errors = []
    if not re.fullmatch(r"[a-z0-9_]+", cap.get("name", "")):
        errors.append("name must use lowercase letters, numbers and underscores")
    if len(cap.get("description", "")) < 15:
        errors.append("description needs at least 15 characters so search can find it")
    if not re.fullmatch(r"(https://|mcp://|local://)\S+", cap.get("endpoint", "")):
        errors.append("endpoint must start with https://, mcp:// or local://")
    if not re.fullmatch(r"\d+\.\d+\.\d+", cap.get("version", "")):
        errors.append("version must look like 1.0.0")
    if not cap.get("owner"):
        errors.append("an owner is required")
    if not cap.get("domain"):
        errors.append("a business domain is required")
    if not cap.get("allowed_groups"):
        errors.append("at least one allowed group is required")
    if cap.get("type") == "mcp":
        cfg = cap.get("mcp") or {}
        if not cfg.get("command"):
            errors.append("an mcp capability needs mcp.command")
        if not cfg.get("allowed_tools"):
            errors.append("an mcp capability needs mcp.allowed_tools (least privilege: list the safe tools)")
    if cap.get("status") not in VALID_STATUSES:
        errors.append(f"status must be one of {sorted(VALID_STATUSES)}")
    return errors
