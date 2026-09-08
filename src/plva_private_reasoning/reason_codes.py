"""Fixed reason and error codes. The UI renders human text locally; the API never explains."""

from typing import Final

APPROVE_REASONS: Final = frozenset(
    {
        "POLICY_MATCH",
        "POLICY_MISSING",
        "CLASS_BLOCKED",
        "DESTINATION_UNVERIFIED",
        "ORIGIN_NOT_ALLOWED",
        "FIELD_NOT_ALLOWED",
        "TOOL_NOT_ALLOWED",
        "SCOPE_EXCEEDED",
        "MODEL_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
    }
)

COMPUTE_REASONS: Final = frozenset(
    {
        "COMPLETED",
        "INVALID_ITEMS",
        "COUNT_MISMATCH",
        "NOT_READY",
        "MODEL_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
    }
)

TRACE_REASONS: Final = frozenset(
    {
        "NOMINAL",
        "SUSPICIOUS_ACTIVITY",
        "BLOCKED_CLASS_ATTEMPT",
        "REPEATED_DENIALS",
        "DESTINATION_MISMATCH",
        "TOKEN_INVALID",
        "MODEL_UNAVAILABLE",
        "MODEL_OUTPUT_INVALID",
    }
)

ERROR_CODES: Final = frozenset(
    {
        "UNAUTHORIZED",
        "FORBIDDEN_HOST",
        "FORBIDDEN_ORIGIN",
        "SCHEMA_INVALID",
        "PAYLOAD_TOO_LARGE",
        "UNSUPPORTED_MEDIA_TYPE",
        "DUPLICATE_REQUEST",
        "NOT_READY",
        "INTERNAL_ERROR",
    }
)
