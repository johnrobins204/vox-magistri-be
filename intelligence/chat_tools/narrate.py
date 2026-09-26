def run_narrate_tool(args, session, game, session_run):
    from dndnd.config import get_settings
    from dndnd.intelligence.client import OllamaClient
    from dndnd.intelligence.game_chat import PromptStage, build_normal_narration, strip_preamble

    settings = get_settings()
    client = OllamaClient(settings)
    model_name = settings.ollama_model

    prompt = build_normal_narration(
        game=game,
        session_run=session_run,
        voice_key="dm_voice",
        user_input=args,
    )

    raw = client.generate(prompt)
    response, preamble = strip_preamble(raw)

    stages = [
        PromptStage(
            name="Narrate",
            model=model_name,
            prompt=prompt,
            raw_response=raw,
            parsed_response=response,
            stripped_preamble=preamble,
        )
    ]

    return response, stages
