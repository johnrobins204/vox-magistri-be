import argparse
import asyncio
import os
import sys
from typing import Sequence

from uvicorn import Config, Server

from app.factory import create_app
from app.deps import get_inference_service
from app.services.logger import init_logging, get_logger
from app.services.build_services import build_services
from app.services.repos import DEFAULT_REPOS, make_default_repos, seed_sample_data

logger = get_logger("dnd_app")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

def parse_args(argv: Sequence[str] | None = None):
    p = argparse.ArgumentParser(prog="dnd-server")
    p.add_argument("--host", default=os.getenv("DND_HOST", DEFAULT_HOST))
    p.add_argument("--port", type=int, default=int(os.getenv("DND_PORT", DEFAULT_PORT)))
    p.add_argument("--seed", action="store_true")
    p.add_argument("--no-tools", action="store_true")
    p.add_argument("--debug", action="store_true")
    return p.parse_args(argv)

async def _run_uvicorn(app, host: str, port: int, reload: bool = False):
    config = Config(app=app, host=host, port=port, reload=reload)
    server = Server(config=config)
    await server.serve()

def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    init_logging(log_dir=os.getenv("DND_LOG_DIR", "logs"), debug_enabled=args.debug)
    logger.info("Starting DnD server", extra={"debug": args.debug})

    try:
        repos = DEFAULT_REPOS if DEFAULT_REPOS else make_default_repos()
    except Exception:
        logger.exception("Failed to load DEFAULT_REPOS")
        repos = make_default_repos()

    if args.seed:
        try:
            seed_sample_data(repos)
        except Exception:
            logger.exception("Failed to seed sample data")

    try:
        services = build_services(repos, enable_tool_discovery=not args.no_tools)
    except Exception:
        logger.exception("Failed to build services")
        return 1

    try:
        app = create_app(services=services)
    except Exception:
        logger.exception("Failed to create FastAPI app")
        return 1

    async def _shutdown_services():
        inference = get_inference_service()
        shutdown_coro = getattr(inference, "shutdown", None)
        if shutdown_coro:
            await shutdown_coro()

    try:
        asyncio.run(_run_uvicorn(app, host=args.host, port=args.port, reload=args.debug))
    except KeyboardInterrupt:
        asyncio.run(_shutdown_services())
        return 0
    except Exception:
        logger.exception("Unhandled exception")
        asyncio.run(_shutdown_services())
        return 1

    asyncio.run(_shutdown_services())
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
