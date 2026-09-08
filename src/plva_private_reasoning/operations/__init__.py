"""Approve, compute, and review-trace implementations with deterministic guards."""


class BackendOutputError(Exception):
    """A backend produced output that failed strict validation (after any retry).

    Backends raise this (or a subclass) so operations report MODEL_OUTPUT_INVALID instead of
    MODEL_UNAVAILABLE. The message must never contain model output or private values.
    """
