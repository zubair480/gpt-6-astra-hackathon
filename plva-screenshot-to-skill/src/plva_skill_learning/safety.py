"""A small second outbound check, not a redaction service or privacy proof."""
import json
import re

from .common import SkillforgeError, TOKEN_PATTERN

_CHECKS = (
    ("canary_detected", r"(?i)(?:PLVA[_-]?CANARY|CANARY[_-]?(?:SECRET|PRIVATE)|SYNTHETIC[_-]?SECRET|DO_NOT_EXPORT)"),
    ("email_detected", r"\b[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b"),
    ("credential_detected", r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?i:bearer\s+[A-Za-z0-9._~-]{12,})"),
    ("scope_escape_detected", r"(?i)(?:ignore (?:all |the )?(?:previous|prior|system) instructions|bypass (?:the |all )?(?:privacy|policy|permissions|approval|security)|(?:reveal|exfiltrate|dump|send) (?:all |the )?(?:secrets|credentials|vault)|disable (?:the )?(?:privacy|redaction|safety)|(?:grant|elevate) (?:yourself |my |all )?(?:permissions|privileges)|(?:execute|run) (?:arbitrary |this )?(?:shell|javascript|powershell|bash|python) (?:code|script|command))"),
)


def findings(value, allow_tokens=False):
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True)
    result = [code for code, pattern in _CHECKS if re.search(pattern, text)]
    if not allow_tokens and re.search(TOKEN_PATTERN, text):
        result.append("session_token_detected")
    return result


def check_outbound(value, allow_tokens=False):
    detected = findings(value, allow_tokens=allow_tokens)
    if detected:
        raise SkillforgeError("outbound_blocked", "Outbound check blocked content: " + ", ".join(detected) + ". Review the source locally.")
