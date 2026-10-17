"""uvicorn target: ``uvicorn aos.api.main:app``."""

from .app import create_app

app = create_app()
