# app/factory.py
from api.v1 import sessions, intelligence, ws
from app.deps import set_services
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from services.logger import get_logger

logger = get_logger(__name__)

def create_app(*, services, title: str = "DnD DM Server") -> FastAPI:
    """
    Create and configure the FastAPI app, wiring the provided services into deps.
    The `services` object should be the same dict or dataclass returned by build_services().
    """
    # Make services available to dependency providers
    set_services(services)

    app = FastAPI(title=title)

    # CORS - adjust origins for your dev environment
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ------------------------------------------------------------
    # Include Routers (v1 API)
    # ------------------------------------------------------------
    app.include_router(sessions.router)       # /api/v1/sessions/...
    app.include_router(intelligence.router)   # /api/v1/intel/...
    app.include_router(ws.router)             # /api/v1/ws/...

    # ------------------------------------------------------------
    # Startup hook: optional warmup
    # ------------------------------------------------------------
    @app.on_event("startup")
    async def _on_startup():
        logger.info("App startup: checking services")
        inference = services.get("inference") or getattr(services, "inference", None)
        if inference is not None and getattr(inference, "model_loaded", False):
            logger.info("Inference model loaded")
        else:
            logger.info("Inference model not loaded or not provided")

    # ------------------------------------------------------------
    # Shutdown hook: graceful cleanup
    # ------------------------------------------------------------
    @app.on_event("shutdown")
    async def _on_shutdown():
        logger.info("App shutdown: cleaning up services")
        inference = services.get("inference") or getattr(services, "inference", None)
        if inference is not None:
            shutdown_coro = getattr(inference, "shutdown", None)
            if shutdown_coro:
                try:
                    await shutdown_coro()
                except Exception:
                    logger.exception("Error shutting down inference service")

    return app
