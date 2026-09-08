"""Per-session placeholder vault: value <-> token mapping that never leaves this process.

Tokens look like ``EMAIL_1_a3f9``: class, per-class counter, 4-hex session nonce. Blocked classes
never get a token; their values are remembered only so outbound text can be scrubbed. Nothing here
is persisted or logged.
"""

from __future__ import annotations

import re
import secrets
from typing import Final

from .types import Level, PiiClass

TOKEN_RE: Final = re.compile(r"^([A-Z][A-Z0-9_]*)_([1-9][0-9]*)_([0-9a-f]{4})$")


class Vault:
    """Session-scoped token store. ``policy`` maps PII class -> level."""

    def __init__(self, policy: dict[str, Level], nonce: str | None = None) -> None:
        if nonce is not None and not re.fullmatch(r"[0-9a-f]{4}", nonce):
            raise ValueError("nonce must be 4 lowercase hex chars")
        self._policy: dict[str, Level] = dict(policy)
        self._nonce: str = nonce if nonce is not None else secrets.token_hex(2)
        self._by_key: dict[tuple[str, str], str] = {}  # (class, value) -> token
        self._by_token: dict[str, tuple[str, str]] = {}  # token -> (class, value)
        self._counters: dict[str, int] = {}
        self.blocked_values: set[str] = set()

    # -- properties -----------------------------------------------------------------------------

    @property
    def nonce(self) -> str:
        return self._nonce

    @property
    def policy(self) -> dict[str, Level]:
        return dict(self._policy)

    def level_for_class(self, pii_class: str) -> Level | None:
        return self._policy.get(pii_class)

    # -- issuance -------------------------------------------------------------------------------

    def issue(self, pii_class: PiiClass | str, value: str) -> str | None:
        """Return the token for ``value`` (minting one if new), or None if the class is blocked."""
        if not value:
            return None
        level = self._policy.get(pii_class)
        if level == "blocked":
            self.blocked_values.add(value)
            return None
        key = (pii_class, value)
        token = self._by_key.get(key)
        if token is not None:
            return token
        n = self._counters.get(pii_class, 0) + 1
        self._counters[pii_class] = n
        token = f"{pii_class}_{n}_{self._nonce}"
        if TOKEN_RE.match(token) is None:  # pragma: no cover - class names are validated literals
            raise ValueError("generated token does not match TOKEN_PATTERN")
        self._by_key[key] = token
        self._by_token[token] = (pii_class, value)
        return token

    # -- lookup ---------------------------------------------------------------------------------

    def _valid_token(self, token: str) -> bool:
        m = TOKEN_RE.match(token or "")
        return m is not None and m.group(3) == self._nonce and token in self._by_token

    def resolve(self, token: str) -> str | None:
        """Real value for a token minted in this session; None for unknown/forged tokens."""
        if not self._valid_token(token):
            return None
        return self._by_token[token][1]

    def class_of(self, token: str) -> str | None:
        if not self._valid_token(token):
            return None
        return self._by_token[token][0]

    def level_of(self, token: str) -> Level | None:
        cls = self.class_of(token)
        if cls is None:
            return None
        return self._policy.get(cls)

    def entries(self) -> list[tuple[str, str, Level]]:
        """(token, class, level) for every minted token. Value-free."""
        out: list[tuple[str, str, Level]] = []
        for token, (cls, _value) in self._by_token.items():
            out.append((token, cls, self._policy.get(cls, "hide_use")))
        return out

    # -- scrubbing / leak checks ----------------------------------------------------------------

    def values_longest_first(self) -> list[tuple[str, str | None]]:
        """Every known value (tokenised and blocked) as (value, token|None), longest first."""
        items: list[tuple[str, str | None]] = [
            (value, token) for token, (_cls, value) in self._by_token.items()
        ]
        items.extend((value, None) for value in self.blocked_values)
        items.sort(key=lambda it: (-len(it[0]), it[0]))
        return items

    def contains_value(self, text: str) -> bool:
        """True if any stored value (tokenised or blocked) appears verbatim in ``text``."""
        if not text:
            return False
        for _token, (_cls, value) in self._by_token.items():
            if value and value in text:
                return True
        return any(value and value in text for value in self.blocked_values)

    def clear(self) -> None:
        self._by_key.clear()
        self._by_token.clear()
        self._counters.clear()
        self.blocked_values.clear()

    def __len__(self) -> int:
        return len(self._by_token)

    def __repr__(self) -> str:  # never reveal values
        return f"Vault(tokens={len(self._by_token)}, blocked={len(self.blocked_values)})"
