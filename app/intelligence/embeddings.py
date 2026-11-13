import logging
import math

import httpx

logger = logging.getLogger(__name__)

OLLAMA_EMBED_URL = "http://localhost:11434/api/embeddings"
DEFAULT_EMBED_MODEL = "nomic-embed-text"  # Fast, local embedding model


async def get_embedding(text: str, client: httpx.AsyncClient | None = None) -> list[float]:
    """Fetches a vector embedding array for a given text string from Ollama."""
    payload = {"model": DEFAULT_EMBED_MODEL, "prompt": text}

    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        own_client = True

    try:
        response = await client.post(OLLAMA_EMBED_URL, json=payload)
        response.raise_for_status()
        return response.json().get("embedding", [])
    except Exception as e:
        logger.error(f"Embedding failed for text '{text[:20]}...': {e}")
        return []
    finally:
        if own_client:
            await client.aclose()


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Pure Python cosine similarity (matches C# pgvector <=> operator behavior)."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0

    dot_product = sum(a * b for a, b in zip(v1, v2, strict=False))
    magnitude1 = math.sqrt(sum(a * a for a in v1))
    magnitude2 = math.sqrt(sum(b * b for b in v2))

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)
