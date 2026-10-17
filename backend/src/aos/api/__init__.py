"""The kernel HTTP API (FastAPI). ``create_app()`` builds it; ``aos.api.main:app`` is the uvicorn target."""

from .app import create_app

__all__ = ["create_app"]
