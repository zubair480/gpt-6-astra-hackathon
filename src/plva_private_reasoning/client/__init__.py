"""Thin fail-closed client for the PLVA private reasoning service (standard library only)."""

from .client import (
    MODEL_UNAVAILABLE,
    NOT_READY,
    ClientError,
    PrivateReasoningClient,
    closed_approve,
    closed_compute,
    closed_review,
    load_credential,
)

__all__ = [
    "MODEL_UNAVAILABLE",
    "NOT_READY",
    "ClientError",
    "PrivateReasoningClient",
    "closed_approve",
    "closed_compute",
    "closed_review",
    "load_credential",
]
