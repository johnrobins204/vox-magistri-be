# app/api/v1/session.py (top imports)
from typing import List, Optional, Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, WebSocket, Header, status, Response
from fastapi.responses import JSONResponse

from app.schemas.v1 import SessionCreateResp, MessageCreateReq, MessageResp
from app.deps import get_session_store, get_inference_service, require_local_token
from app.logger import get_logger
from app.types import SessionStore, InferenceService  # <-- new typed Protocols

router = APIRouter(prefix="/api/v1", tags=["sessions"])
logger = get_logger(__name__)

# defaults
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5000

logger = get_logger("dnd_app")

def parse_args(argv: Sequence[str] | None = None):
    p = argparse.ArgumentParser(prog="dnd-server")
    p.add_argument("--host", default=os.getenv("DND_HOST", DEFAULT_HOST))
    p.add_argument("--port", type=int, default=int(os.getenv("DND_PORT", DEFAULT_PORT)))
    p.add_argument("--seed", action="store_true", help="Seed sample data into repos on startup")
    p.add_argument("--no-tools", action="store_true", help="Disable tool discovery in services")
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p.parse_args(argv)

async def _run_uvicorn(app, host: str, port: int, reload: bool = False):
    config = Config(app=app, host=host, port=port, log_config=None, loop="asyncio", reload=reload)
    server = Server(config=config)
    await server.serve()

def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    # initialize logging once, early
    init_logging(log_dir=os.getenv("DND_LOG_DIR", "logs"), debug_enabled=args.debug)
    logger.info("Starting DnD server main", extra={"debug": args.debug})

    # Create repos
    try:
        repos = DEFAULT_REPOS if DEFAULT_REPOS else make_default_repos()
    except Exception:
        logger.exception("Failed to load DEFAULT_REPOS; falling back to make_default_repos()")
        repos = make_default_repos()

    # Seed if requested
    if args.seed:
        try:
            seed_sample_data(repos)
            logger.info("Seeded sample data into repos.")
        except Exception:
            logger.exception("Failed to seed sample data")

    # Build services
    try:
        services = build_services(repos, enable_tool_discovery=not args.no_tools)
    except Exception:
        logger.exception("Failed to build services")
        return 1

    # Create FastAPI app and wire services
    try:
        app = create_app(services=services)
    except Exception:
        logger.exception("Failed to create FastAPI app")
        return 1

    # graceful shutdown helper
    async def _shutdown_services():
        try:
            inference = get_inference_service()
            shutdown_coro = getattr(inference, "shutdown", None)
            if shutdown_coro:
                logger.info("Shutting down inference service")
                await shutdown_coro()
        except Exception:
            logger.exception("Error during service shutdown")

    # Run server
    try:
        asyncio.run(_run_uvicorn(app, host=args.host, port=args.port, reload=args.debug))
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt, shutting down")
        try:
            asyncio.run(_shutdown_services())
        except Exception:
            logger.exception("Error during shutdown after KeyboardInterrupt")
        return 0
    except Exception:
        logger.exception("Unhandled exception in server runtime")
        try:
            asyncio.run(_shutdown_services())
        except Exception:
            logger.exception("Error during shutdown after exception")
        return 1

    # Normal exit cleanup
    try:
        asyncio.run(_shutdown_services())
    except Exception:
        logger.exception("Error during final shutdown")

    logger.info("Server exited cleanly")
    return 0

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
