# services/build_services.py

from typing import Any

from app.config import get_settings
from app.services.game_service import GameService
from app.services.inference_service import OllamaInferenceService
from app.services.tool_service import ToolService


def build_services(repos: dict[str, Any], enable_tool_discovery: bool = True) -> dict[str, Any]:
    """
    Construct all runtime services used by the API layer.
    """

    session_store = repos.get("session")

    settings = get_settings()

    inference = OllamaInferenceService(settings)

    tool_service = ToolService(
        default_context={"repos": repos, "inference": inference},
        discover_on_init=enable_tool_discovery,
    )

    game_service = GameService()

    return {
        "session": session_store,
        "tool": tool_service,
        "game": game_service,
        "inference": inference,
    }
