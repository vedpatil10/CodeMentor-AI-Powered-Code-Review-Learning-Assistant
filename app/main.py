"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.webhooks import router as webhooks_router
from app.config import Settings
from app.db.deliveries import DeliveryStore


def create_app(
    settings: Settings | None = None,
    delivery_store: DeliveryStore | None = None,
) -> FastAPI:
    application = FastAPI(title="CodeMentor", version="0.1.0")
    application.state.settings = settings or Settings.from_env()
    application.state.delivery_store = delivery_store or DeliveryStore(
        application.state.settings.database_path
    )
    application.include_router(health_router)
    application.include_router(webhooks_router)
    return application


app = create_app()