# services/inference_service.py

from app.intelligence.client import OllamaClient
from app.services.logger import get_logger

logger = get_logger(__name__)


class OllamaInferenceService:
    """
    Minimal viable inference adapter that connects the FastAPI backend
    to your existing intelligence/ Ollama client.

    This satisfies the InferenceService interface expected by the API layer.
    """

    def __init__(self, settings):
        # settings must provide ollama_base_url and ollama_model
        self.client = OllamaClient(
            base_url=settings.ollama.base_url,
            default_model=settings.ollama.model,
        )
        self.model_loaded = True

    # ------------------------------------------------------------
    # Queueing (minimal stub for now)
    # ------------------------------------------------------------
    def enqueue(self, *, session_id: str, message_id: str, prompt: str, store) -> bool:
        # No queue yet — always accept
        return True

    def queue_position(self, message_id: str):
        # No queue yet — always 0
        return 0

    def estimate_wait(self, message_id: str):
        # No queue yet — always 0
        return 0.0

    # ------------------------------------------------------------
    # Token generation (non-streaming for now)
    # ------------------------------------------------------------
    async def generate_tokens(self, *, prompt: str, session_id: str | None, message_id: str):
        """
        For now, call Ollama synchronously and yield the full response as one token.
        Later we can switch to Ollama's streaming API.
        """
        try:
            text = self.client.generate(prompt)
            yield text
        except Exception as exc:
            logger.exception("Ollama generate failed")
            yield f"[error] {exc}"

    # ------------------------------------------------------------
    # Cancellation (stub)
    # ------------------------------------------------------------
    def cancel(self, message_id: str) -> bool:
        return True

    # ------------------------------------------------------------
    # Token validation (stub)
    # ------------------------------------------------------------
    def validate_token(self, token: str) -> bool:
        return True

    # ------------------------------------------------------------
    # Shutdown hook
    # ------------------------------------------------------------
    async def shutdown(self):
        pass
