# services/build_services.py

from typing import Any, Dict

from services.session_service import SessionService
from services.tool_service import ToolService
from services.game_service import GameService

class InferenceStub:
    model_loaded = False

    def enqueue(self, *, session_id: str, message_id: str, prompt: str, store) -> bool:
        return True

    def cancel(self, message_id: str) -> bool:
        return True

    def validate_token(self, token: str) -> bool:
        return True

    def queue_position(self, message_id: str):
        return 0

    def estimate_wait(self, message_id: str):
        return 0.0

    async def generate_tokens(self, *, prompt: str, session_id: str | None, message_id: str):
        yield prompt

    async def shutdown(self):
        pass


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

    inference_service = InferenceStub()

    return {
        "session": session_store,
        "tool": tool_service,
        "game": game_service,
        "inference": inference_service,
    }
