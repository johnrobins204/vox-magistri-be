"""
Version 1 API namespace.

Routers exposed here:
- intelligence: intelligence-related endpoints
- reference: read-only reference data (species catalog)
- session: chat/session lifecycle endpoints
- ws: WebSocket endpoints
"""

from app.api.v1 import intelligence, reference, session, ws

__all__ = ["session", "intelligence", "reference", "ws"]
