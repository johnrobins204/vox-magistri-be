# app/deps.py
from typing import Any

from fastapi import Depends, Header, HTTPException

# Module-level container for services. create_app() will call set_services().
_services: Any | None = None

def set_services(services: Any) -> None:
    """
    Called once at app creation time to make the services available to dependency functions.
    `services` can be a dict or a dataclass with attributes like 'inference', 'session', 'tool', etc.
    """
    global _services
    _services = services

# Dependency getters used by routers
def get_services():
    if _services is None:
        raise RuntimeError("Services not configured. Call create_app(services=...) first.")
    return _services

def get_inference_service():
    s = get_services()
    # support both dict and attribute access
    return s.get("inference") if isinstance(s, dict) else getattr(s, "inference", None)

def get_session_store():
    s = get_services()
    return s.get("session") if isinstance(s, dict) else getattr(s, "session", None)

def get_tool_service():
    s = get_services()
    return s.get("tool") if isinstance(s, dict) else getattr(s, "tool", None)



# existing set_services/get_* functions...

def require_local_token(authorization: str | None = Header(None)):
    # simple example: expect "Bearer <token>"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")
    token = authorization.split(" ", 1)[1]
    # optionally validate token here or via inference.validate_token in handlers
    return token
