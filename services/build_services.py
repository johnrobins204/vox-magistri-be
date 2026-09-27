# services/build_services.py

from typing import Any, Dict

from services.session_service import SessionService
from services.tool_service import ToolService
from services.game_service import GameService
from services.inference_service import OllamaInferenceService
from app.config import get_settings

def build_services(repos: Dict[str, Any], enable_tool_discovery: bool = True) -> Dict[str, Any]:
    """
    Construct all runtime services used by the API layer.
    """

    session_store = repos.get("session")

    tool_service = ToolService(
        default_context={"repos": repos},
        discover_on_init=enable_tool_discovery
    )

    game_service = GameService()

    settings = get_settings()

    inference = OllamaInferenceService(settings)

    return {
        "session": session_store,
        "tool": tool_service,
        "game": game_service,
        "inference": inference,
    }
