def run_clear_tool(args, session, game, session_run):
    session_run.entries.clear()
    session.commit()
    return "Conversation history cleared.", []
