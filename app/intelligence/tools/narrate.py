# app/intelligence/tools/narrate.py

NAME = "narrate"

def run(args: dict, context: dict):
    """
    Modern narration tool.
    Uses the unified inference service and prompt builders.
    """

    # Extract context
    game = context.get("game")
    session_run = context.get("session_run")
    inference = context.get("inference")

    # Extract user input
    user_text = args.get("text") or args.get("input") or ""

    # Build narration prompt using your unified prompt builder
    from app.intelligence.prompt_builders import build_narrator_prompt

    prompt = build_narrator_prompt(
        game=game,
        session_run=session_run,
        user_input=user_text,
        voice_key="dm_voice",
    )

    # Generate text using the central inference service
    raw = inference.generate(prompt)

    # Return normalized tool output
    return {
        "text": raw,
        "meta": {
            "prompt": prompt,
            "tool": NAME,
        }
    }
