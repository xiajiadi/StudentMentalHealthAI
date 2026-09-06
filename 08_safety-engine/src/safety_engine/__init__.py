"""Independent Safety Control Plane for StudentMentalHealthAI."""

from .client import SafetyClient, SafetyClientError

__version__ = "0.1.0"

__all__ = ["SafetyClient", "SafetyClientError", "__version__"]
