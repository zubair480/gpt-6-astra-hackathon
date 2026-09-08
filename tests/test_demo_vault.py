"""Unit tests for the per-session placeholder vault."""

from __future__ import annotations

import re

import pytest

from plva_agent_demo.types import DEFAULT_POLICY, Level
from plva_agent_demo.vault import Vault
from plva_private_reasoning.contracts import TOKEN_PATTERN

POLICY: dict[str, Level] = dict(DEFAULT_POLICY)


def test_nonce_is_four_hex_and_tokens_match_contract_pattern() -> None:
    v = Vault(POLICY)
    assert re.fullmatch(r"[0-9a-f]{4}", v.nonce)
    tok = v.issue("EMAIL", "a@example.invalid")
    assert tok is not None
    assert re.match(TOKEN_PATTERN, tok)
    assert tok == f"EMAIL_1_{v.nonce}"


def test_explicit_nonce_validated() -> None:
    assert Vault(POLICY, "abcd").nonce == "abcd"
    with pytest.raises(ValueError):
        Vault(POLICY, "ABCD")
    with pytest.raises(ValueError):
        Vault(POLICY, "abcde")


def test_issue_counts_per_class_and_dedupes_same_value() -> None:
    v = Vault(POLICY, "abcd")
    e1 = v.issue("EMAIL", "a@example.invalid")
    e2 = v.issue("EMAIL", "b@example.invalid")
    p1 = v.issue("PHONE", "+1 415 555 0142")
    assert (e1, e2, p1) == ("EMAIL_1_abcd", "EMAIL_2_abcd", "PHONE_1_abcd")
    assert v.issue("EMAIL", "a@example.invalid") == e1  # same (class, value) -> same token
    assert v.issue("NAME", "a@example.invalid") == "NAME_1_abcd"  # different class -> new token
    assert len(v) == 4


def test_resolve_class_level_entries() -> None:
    v = Vault(POLICY, "abcd")
    tok = v.issue("API_KEY", "sk-live-0123456789abcdef0123456789")
    assert tok == "API_KEY_1_abcd"
    assert v.resolve(tok) == "sk-live-0123456789abcdef0123456789"
    assert v.class_of(tok) == "API_KEY"
    assert v.level_of(tok) == "approval"
    assert v.entries() == [("API_KEY_1_abcd", "API_KEY", "approval")]
    # entries() is value-free
    assert "sk-live" not in repr(v.entries())
    assert "sk-live" not in repr(v)


def test_blocked_classes_get_no_token_but_are_remembered_for_scrubbing() -> None:
    v = Vault(POLICY, "abcd")
    assert v.issue("PASSWORD", "hunter2") is None
    assert v.issue("SSN", "078-05-1120") is None
    assert v.blocked_values == {"hunter2", "078-05-1120"}
    assert v.entries() == []
    assert v.resolve("PASSWORD_1_abcd") is None
    assert v.contains_value("my password is hunter2!")
    assert ("hunter2", None) in v.values_longest_first()


def test_forged_or_foreign_nonce_never_resolves() -> None:
    v = Vault(POLICY, "abcd")
    tok = v.issue("EMAIL", "a@example.invalid")
    assert tok == "EMAIL_1_abcd"
    assert v.resolve("EMAIL_1_ffff") is None
    assert v.resolve("EMAIL_2_abcd") is None  # never minted
    assert v.resolve("EMAIL_1_abcd ") is None
    assert v.resolve("email_1_abcd") is None
    assert v.resolve("") is None
    assert v.class_of("EMAIL_1_ffff") is None
    assert v.level_of("EMAIL_1_ffff") is None
    other = Vault(POLICY, "ffff")
    other.issue("EMAIL", "a@example.invalid")
    assert other.resolve(tok) is None


def test_leak_check_and_longest_first_ordering() -> None:
    v = Vault(POLICY, "abcd")
    v.issue("NAME", "Alice")
    v.issue("EMAIL", "alice.example@example.invalid")
    v.issue("PASSWORD", "hunter2-synthetic")
    values = [val for val, _tok in v.values_longest_first()]
    assert values == ["alice.example@example.invalid", "hunter2-synthetic", "Alice"]
    assert v.contains_value("contact alice.example@example.invalid now")
    assert v.contains_value("...hunter2-synthetic...")
    assert not v.contains_value("nothing here")
    assert not v.contains_value("")


def test_empty_value_is_never_tokenised() -> None:
    v = Vault(POLICY, "abcd")
    assert v.issue("EMAIL", "") is None
    assert len(v) == 0


def test_unknown_class_defaults_to_tokenised() -> None:
    v = Vault({"EMAIL": "hide_use"}, "abcd")
    assert v.issue("PHONE", "5550142") == "PHONE_1_abcd"
    assert v.level_of("PHONE_1_abcd") is None
    assert v.entries() == [("PHONE_1_abcd", "PHONE", "hide_use")]


def test_clear_forgets_everything_but_keeps_nonce() -> None:
    v = Vault(POLICY, "abcd")
    v.issue("EMAIL", "a@example.invalid")
    v.issue("SSN", "078-05-1120")
    v.clear()
    assert len(v) == 0
    assert v.blocked_values == set()
    assert v.resolve("EMAIL_1_abcd") is None
    assert v.nonce == "abcd"
    assert v.issue("EMAIL", "a@example.invalid") == "EMAIL_1_abcd"  # counters reset
