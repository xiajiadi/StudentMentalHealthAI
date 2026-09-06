"""Internal FastAPI surface for the Safety Control Plane."""

from .app import create_app

__all__ = ["create_app"]
