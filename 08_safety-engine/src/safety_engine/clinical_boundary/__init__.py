"""Guardrails against unsupported clinical inference or diagnosis."""

from .guard import ClinicalBoundaryGuard

__all__ = ["ClinicalBoundaryGuard"]
