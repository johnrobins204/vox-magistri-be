import logging
from app.services.logger import get_logger

logger = get_logger(__name__)

async def expand_query_for_5e(query: str, client = None) -> list[str]:
    """
    Translates a natural language player question into canonical 5e terms 
    using the centralized Ollama client.
    """
    if not client:
        return []

    prompt = f"""You are a D&D 5e rules parser.
The player asked: "{query}"

List 3 to 5 official D&D 5e mechanical terms, conditions, actions, or skills relevant to answering this.
Return ONLY a comma-separated list. No introductory text, no markdown, no explanations."""

    try:
        # Use the project's standardized generate method or client
        if hasattr(client, "generate"):
            result_text = client.generate(prompt)
        elif hasattr(client, "chat"):
            # Fallback if chat is required
            result_text = client.chat([{"role": "user", "content": prompt}])
        else:
            return []

        expanded_terms = [
            term.strip().lower() 
            for term in result_text.strip().split(",") 
            if term.strip()
        ]
        
        logger.info(f"Query Expansion: '{query}' -> {expanded_terms}")
        return expanded_terms

    except Exception as e:
        logger.error(f"Query expansion failed: {e}")
        return []