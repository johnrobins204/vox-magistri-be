"""SPEC-0011 WP-3: species catalog wired into services and tool context (T-19..T-20).

No test opens a network connection or needs Ollama.
"""

import asyncio

from app.services.build_services import build_services
from app.services.repos import make_default_repos


def _build():
    services = build_services(make_default_repos(), enable_tool_discovery=False)
    return services


def test_t19_services_reference_holds_68_species():
    services = _build()
    try:
        assert len(services["reference"]["species"]) == 68
    finally:
        asyncio.run(services["inference"].shutdown())


def test_t20_tool_context_reference_is_the_services_reference_object():
    services = _build()
    try:
        assert services["tool"].default_context["reference"] is services["reference"]
    finally:
        asyncio.run(services["inference"].shutdown())
