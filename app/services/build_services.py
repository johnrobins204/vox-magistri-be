# services/build_services.py

from typing import Any

from app.config import get_settings
from app.reference.loader import load_entries
from app.reference.rules import RULES_PATH, Rule
from app.reference.species import load_species
from app.reference.weapons import WEAPONS_PATH, Weapon
from app.services.inference_service import OllamaInferenceService
from app.services.tool_service import ToolService


def build_services(repos: dict[str, Any], enable_tool_discovery: bool = True) -> dict[str, Any]:
    """
    Construct all runtime services used by the API layer.

    Order matters (ADR-0004 D1, ADR-0008 D2): the ToolService is built first, the reference
    catalog next so the worker can read species, then the inference service, which gets the
    ToolService so the worker can dispatch slash commands. Last, the inference service is
    added to the tool context.
    """

    session_store = repos.get("session")

    settings = get_settings()

    tool_service = ToolService(
        default_context={"repos": repos},
        discover_on_init=enable_tool_discovery,
    )

    reference = {
        "species": load_species(),
        "weapons": load_entries(WEAPONS_PATH, Weapon, "weapons"),
        "rules": load_entries(RULES_PATH, Rule, "rules"),
    }

    inference = OllamaInferenceService(
        settings, tool_service=tool_service, species=reference["species"]
    )
    tool_service.default_context["inference"] = inference
    tool_service.default_context["reference"] = reference

    return {
        "session": session_store,
        "tool": tool_service,
        "inference": inference,
        "reference": reference,
    }
