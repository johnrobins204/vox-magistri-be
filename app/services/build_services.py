# services/build_services.py

from typing import Any

from app.config import get_settings
from app.reference.species import load_species
from app.services.inference_service import OllamaInferenceService
from app.services.tool_service import ToolService


def build_services(repos: dict[str, Any], enable_tool_discovery: bool = True) -> dict[str, Any]:
    """
    Construct all runtime services used by the API layer.

    Order matters (ADR-0004 D1): the ToolService is built first, the inference service is
    given the ToolService so the worker can dispatch slash commands, and only then is the
    inference service added to the tool context.
    """

    session_store = repos.get("session")

    settings = get_settings()

    tool_service = ToolService(
        default_context={"repos": repos},
        discover_on_init=enable_tool_discovery,
    )

    inference = OllamaInferenceService(settings, tool_service=tool_service)
    tool_service.default_context["inference"] = inference

    reference = {"species": load_species()}
    tool_service.default_context["reference"] = reference

    return {
        "session": session_store,
        "tool": tool_service,
        "inference": inference,
        "reference": reference,
    }
