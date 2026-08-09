"""jarvis-osx-api — macOS personal-data bridge (iMessage, Contacts, Shortcuts).

Native-only service (never Docker): needs host TCC grants and a logged-in GUI
session. See prds/osx-api.md in the meta repo for the full design.
"""

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=os.getenv("JARVIS_LOG_CONSOLE_LEVEL", "INFO"))
logger = logging.getLogger("uvicorn")

from fastapi import FastAPI  # noqa: E402

from api import contact_routes, health_routes, message_routes, shortcut_routes  # noqa: E402
from version import __version__  # noqa: E402

app = FastAPI(title="Jarvis OSX API", version=__version__)
app.include_router(health_routes.router)
app.include_router(message_routes.router)
app.include_router(contact_routes.router)
app.include_router(shortcut_routes.router)


def _init_service_config() -> None:
    """Discovery is read-only and optional — the service works without the
    Jarvis stack (auth is our own API keys), but logs route through it."""
    try:
        from jarvis_config_client import init as config_init
    except ImportError:
        logger.info("jarvis-config-client not installed; running standalone")
        return
    try:
        config_init(config_url=os.getenv("JARVIS_CONFIG_URL"), refresh_interval_seconds=300)
    except Exception as exc:  # discovery down ≠ service down
        logger.warning("config-service discovery unavailable: %s", exc)


def _setup_remote_logging() -> None:
    try:
        from jarvis_log_client import JarvisLogHandler, init as init_log_client
    except ImportError:
        logger.info("jarvis-log-client not installed; console logging only")
        return
    app_id = os.getenv("JARVIS_APP_ID", "jarvis-osx-api")
    app_key = os.getenv("JARVIS_APP_KEY")
    if not app_key:
        logger.warning("JARVIS_APP_KEY not set, remote logging disabled")
        return
    init_log_client(app_id=app_id, app_key=app_key)
    remote_level = os.getenv("JARVIS_LOG_REMOTE_LEVEL", "DEBUG")
    handler = JarvisLogHandler(
        service="jarvis-osx-api",
        level=getattr(logging, remote_level.upper(), logging.DEBUG),
    )
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(logger_name).addHandler(handler)


@app.on_event("startup")
async def startup() -> None:
    _init_service_config()
    _setup_remote_logging()
    logger.info("jarvis-osx-api %s started", __version__)
