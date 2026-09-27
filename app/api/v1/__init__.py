"""
Version 1 API namespace.

Routers exposed here:
- session: chat/session lifecycle endpoints
- admin: (optional) admin/debug/tool endpoints
"""

from ....api.v1 import session

# Optional: only import admin if you implement it
try:
    from . import admin
except ImportError:
    admin = None
