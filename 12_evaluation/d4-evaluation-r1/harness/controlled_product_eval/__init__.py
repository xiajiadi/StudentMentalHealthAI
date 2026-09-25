"""Evaluation-only D4-3B controlled product runner."""

from .approved_packet import ApprovedPacket, ApprovedPacketError, load_approved_packet
from .manifest import (
    EXPECTED_RUNTIME_IDENTITY,
    RuntimePreflight,
    build_case_manifest,
    build_formal_manifest,
    verify_formal_manifest,
)
from .runner import run_evaluation

__all__ = [
    "ApprovedPacket",
    "ApprovedPacketError",
    "EXPECTED_RUNTIME_IDENTITY",
    "RuntimePreflight",
    "build_case_manifest",
    "build_formal_manifest",
    "load_approved_packet",
    "run_evaluation",
    "verify_formal_manifest",
]
