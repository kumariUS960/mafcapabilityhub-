"""Small web app on top of the capability-driven agent.

Run:   uvicorn src.web_app:app --reload        then open http://127.0.0.1:8000

With no settings it runs the OFFLINE engine (no model, no cost). Set MODEL_PROVIDER in .env
(github, ollama or foundry) to put a real model behind the same page.

Security note: the user dropdown is a DEMO. Anyone who opens the page can pick any user, including the admin.
A real deployment must take the user and groups from a signed-in identity (for example Microsoft Entra ID),
never from the browser.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .backends import backend_name
from .capabilities import close_mcp_connections
from .engines import create_engine
from .registry import AUDIT, USERS, audit, load_registry, set_status

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class ChatIn(BaseModel):
    session_id: str
    user: str
    message: str


class ApproveIn(BaseModel):
    session_id: str
    approval_id: str
    approved: bool


class StatusIn(BaseModel):
    user: str
    name: str
    status: str


def _user(user_id: str):
    if user_id not in USERS:
        raise HTTPException(404, "Unknown user")
    return USERS[user_id]


def create_app(engine=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        load_dotenv()
        app.state.engine = engine or create_engine()
        yield
        await close_mcp_connections()

    app = FastAPI(title="Capability Hub (MAF)", lifespan=lifespan)

    @app.get("/")
    async def home():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/info")
    async def info():
        return {
            "mode": app.state.engine.mode,
            "registry": backend_name(),
            "users": [{"id": u.id, "name": u.name, "groups": list(u.groups), "admin": u.admin} for u in USERS.values()],
        }

    @app.post("/api/chat")
    async def chat(body: ChatIn):
        user = _user(body.user)
        if not body.message.strip():
            raise HTTPException(400, "Empty message")
        result = await app.state.engine.chat(body.session_id, user, body.message.strip())
        return result.__dict__

    @app.post("/api/approve")
    async def approve(body: ApproveIn):
        result = await app.state.engine.decide(body.session_id, body.approval_id, body.approved)
        return result.__dict__

    @app.get("/api/audit")
    async def get_audit():
        return list(reversed(AUDIT))[:100]

    @app.get("/api/registry")
    async def get_registry(user: str):
        u = _user(user)
        rows = []
        for cap in load_registry():
            rows.append(
                {
                    "name": cap["name"],
                    "type": cap["type"],
                    "description": cap["description"],
                    "status": cap["status"],
                    "groups": cap["allowed_groups"],
                    "requires_approval": cap["requires_approval"],
                    "version": cap["version"],
                    "owner": cap["owner"],
                    "usable": cap["status"] == "active" and bool(set(cap["allowed_groups"]) & set(u.groups)),
                }
            )
        return rows

    @app.post("/api/registry/status")
    async def change_status(body: StatusIn):
        u = _user(body.user)
        if not u.admin:
            audit(u, body.name, "Refused", "only registry admins can change a capability")
            raise HTTPException(403, "Only registry admins can change the registry")
        try:
            set_status(body.name, body.status)
        except KeyError:
            raise HTTPException(404, "Unknown capability")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        audit(u, body.name, "Status changed", f"now {body.status}")
        return {"ok": True}

    return app


app = create_app()
