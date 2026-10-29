"""FastAPI application entry point."""

from fastapi import FastAPI

from app.api.health import router as health_router


def create_app() -> FastAPI:
    application = FastAPI(title="CodeMentor", version="0.1.0")
    application.include_router(health_router)
    return application


app = create_app()