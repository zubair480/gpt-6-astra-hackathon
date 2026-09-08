"""Unit tests for the detectors, painter, redact() and scrub_text() with hand-built spans."""

from __future__ import annotations

import io

import pytest
from PIL import Image

from plva_agent_demo.redact import (
    BLOCKED_LITERAL,
    MASK_FILL,
    detect,
    iban_ok,
    luhn_ok,
    paint,
    redact,
    scrub_text,
)
from plva_agent_demo.types import (
    DEFAULT_POLICY,
    Box,
    Finding,
    Level,
    Mask,
    Snapshot,
    TextSpan,
)
from plva_agent_demo.vault import Vault

POLICY: dict[str, Level] = dict(DEFAULT_POLICY)
ROW_H = 18.0


def span(
    text: str,
    x: float = 400,
    y: float = 100,
    w: float | None = None,
    field_id: str | None = None,
    input_type: str | None = None,
) -> TextSpan:
    box = Box(x, y, w if w is not None else 8.0 * len(text), ROW_H)
    return TextSpan(text=text, box=box, field_id=field_id, input_type=input_type)


def label(text: str, y: float) -> TextSpan:
    return span(text, x=200, y=y)


def by_class(findings: list[Finding], cls: str) -> list[Finding]:
    return [f for f in findings if f.pii_class == cls]


def values(findings: list[Finding], cls: str) -> set[str]:
    return {f.value for f in by_class(findings, cls)}


# --- validators ---------------------------------------------------------------------------------


def test_luhn() -> None:
    assert luhn_ok("4242424242424242")
    assert luhn_ok("5555555555554444")
    assert not luhn_ok("4242424242424241")
    assert not luhn_ok("1234")
    assert not luhn_ok("42424242424242ab")


def test_iban() -> None:
    assert iban_ok("DE89 3704 0044 0532 0130 00")
    assert iban_ok("GB82WEST12345698765432")
    assert not iban_ok("DE89 3704 0044 0532 0130 01")
    assert not iban_ok("DE89")


# --- detectors ----------------------------------------------------------------------------------


def test_email() -> None:
    f = detect([span("Contact: alice.example@example.invalid today")], POLICY)
    assert values(f, "EMAIL") == {"alice.example@example.invalid"}


@pytest.mark.parametrize(
    "text",
    ["+1 415 555 0142", "(415) 555-0142", "415-555-0142", "+44 20 7946 0958", "555-0142"],
)
def test_phone_formats(text: str) -> None:
    assert values(detect([span(text)], POLICY), "PHONE") == {text}


def test_phone_rejects_short_and_dates() -> None:
    assert by_class(detect([span("12345")], POLICY), "PHONE") == []
    assert by_class(detect([span("order 1990-04-12")], POLICY), "PHONE") == []


def test_card_number_luhn_pass_and_reject() -> None:
    ok = detect([span("4242 4242 4242 4242")], POLICY)
    assert values(ok, "CARD_NUMBER") == {"4242 4242 4242 4242"}
    bad = detect([span("4242 4242 4242 4241")], POLICY)
    assert by_class(bad, "CARD_NUMBER") == []
    dashed = detect([span("5555-5555-5555-4444")], POLICY)
    assert values(dashed, "CARD_NUMBER") == {"5555-5555-5555-4444"}


def test_cvc_same_span_and_adjacent_span() -> None:
    f = detect([span("4242 4242 4242 4242 · exp 09/28 · CVC 123")], POLICY)
    assert values(f, "CVC") == {"123"}
    assert values(f, "CARD_NUMBER") == {"4242 4242 4242 4242"}
    adjacent = detect([label("CVV", 100), span("9876", x=400, y=100)], POLICY)
    assert values(adjacent, "CVC") == {"9876"}
    no_context = detect([span("9876")], POLICY)
    assert by_class(no_context, "CVC") == []


def test_ssn() -> None:
    assert values(detect([span("078-05-1120")], POLICY), "SSN") == {"078-05-1120"}
    assert by_class(detect([span("000-05-1120")], POLICY), "SSN") == []


def test_iban_detector_validates_mod97() -> None:
    good = detect([span("DE89 3704 0044 0532 0130 00")], POLICY)
    assert values(good, "BANK_ACCOUNT") == {"DE89 3704 0044 0532 0130 00"}
    bad = detect([span("DE89 3704 0044 0532 0130 01")], POLICY)
    assert by_class(bad, "BANK_ACCOUNT") == []


def test_dob_requires_birth_context_in_row() -> None:
    with_label = detect([label("Date of birth", 100), span("1990-04-12", y=100)], POLICY)
    assert values(with_label, "DOB") == {"1990-04-12"}
    nearby = detect([label("DOB", 100), span("12/04/1990", y=130)], POLICY)  # within 40px
    assert values(nearby, "DOB") == {"12/04/1990"}
    far = detect([label("DOB", 100), span("1990-04-12", y=200)], POLICY)
    assert by_class(far, "DOB") == []
    no_label = detect([label("Created", 100), span("1990-04-12", y=100)], POLICY)
    assert by_class(no_label, "DOB") == []


def test_address_with_and_without_tail() -> None:
    full = "742 Evergreen Terrace, Springfield, OR 97477"
    assert values(detect([span(full)], POLICY), "ADDRESS") == {full}
    assert values(detect([span("Ship to 221B Baker Street now")], POLICY), "ADDRESS") == {
        "221B Baker Street"
    }
    assert values(detect([span("1600 Pennsylvania Ave NW")], POLICY), "ADDRESS") == {
        "1600 Pennsylvania Ave"
    }
    assert by_class(detect([span("42 things")], POLICY), "ADDRESS") == []


@pytest.mark.parametrize(
    "key",
    [
        "sk-live-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
        "sk-abcdefghijklmnopqrstuvwxyz0123",
        "AKIAIOSFODNN7EXAMPLE",
        "ghp_" + "a1" * 18,
        "xoxb-1234567890-abcdefgh",
        "xoxp-1234567890-abcdefgh",
    ],
)
def test_api_key_patterns(key: str) -> None:
    assert values(detect([span(f"key: {key}")], POLICY), "API_KEY") == {key}


def test_api_key_generic_needs_key_label_in_same_row() -> None:
    tok = "Zx9" * 10  # 30 base62 chars
    labelled = detect([label("API key", 100), span(tok, y=100)], POLICY)
    assert values(labelled, "API_KEY") == {tok}
    unlabelled = detect([label("Reference", 100), span(tok, y=100)], POLICY)
    assert by_class(unlabelled, "API_KEY") == []
    # label 35px away is NOT the same row for the generic rule
    other_row = detect([label("API key", 100), span(tok, y=135)], POLICY)
    assert by_class(other_row, "API_KEY") == []


def test_secret_patterns_and_label() -> None:
    whsec = "whsec_9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c"
    assert values(detect([span(whsec)], POLICY), "SECRET") == {whsec}
    tok = "s3cr3t_" + "ab12" * 6
    labelled = detect([label("Client secret", 100), span(tok, y=100)], POLICY)
    assert values(labelled, "SECRET") == {tok}
    # whsec_ is SECRET even when an API-key label is nearby (pattern pass wins)
    both = detect([label("Your API key", 100), span(whsec, y=100)], POLICY)
    assert values(both, "SECRET") == {whsec}
    assert by_class(both, "API_KEY") == []


def test_auth_token_jwt_bearer_and_label() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.synthetic.token-not-real"
    assert values(detect([span(jwt)], POLICY), "AUTH_TOKEN") == {jwt}
    bearer = "Authorization: Bearer abcdef0123456789abcdef0123456789"
    assert values(detect([span(bearer)], POLICY), "AUTH_TOKEN") == {
        "abcdef0123456789abcdef0123456789"
    }
    tok = "tok_" + "q7" * 12
    labelled = detect([label("Session token", 100), span(tok, y=100)], POLICY)
    assert values(labelled, "AUTH_TOKEN") == {tok}
    # dotted hostnames are not JWTs
    host = detect([span("some-long-subdomain-name.example.com")], POLICY)
    assert by_class(host, "AUTH_TOKEN") == []


def test_private_key_block() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIBOgIBAAJBAK\n-----END RSA PRIVATE KEY-----"
    f = detect([span(pem)], POLICY)
    assert values(f, "PRIVATE_KEY") == {pem}


def test_password_input_any_value() -> None:
    s = span("hunter2", field_id="current-password", input_type="password")
    f = detect([s], POLICY)
    assert by_class(f, "PASSWORD") == [
        Finding("PASSWORD", "hunter2", (s.box,), field_id="current-password")
    ]
    # a password value that looks like something else is still only PASSWORD
    s2 = span("alice@example.invalid", field_id="pw", input_type="password")
    f2 = detect([s2], POLICY)
    assert {x.pii_class for x in f2} == {"PASSWORD"}


def test_name_needs_row_label_or_column_header() -> None:
    labelled = detect([label("Full name", 100), span("Alice Example", y=100)], POLICY)
    assert values(labelled, "NAME") == {"Alice Example"}
    unlabelled = detect([label("Plan", 100), span("Alice Example", y=100)], POLICY)
    assert by_class(unlabelled, "NAME") == []
    table = detect(
        [
            span("Name", x=260, y=100),
            span("Email", x=520, y=100),
            span("Charlie Example", x=260, y=140),
            span("charlie@example.invalid", x=520, y=140),
            span("Bob Example", x=260, y=170),
        ],
        POLICY,
    )
    assert values(table, "NAME") == {"Charlie Example", "Bob Example"}
    # label itself is not a name
    assert "Full Name" not in values(
        detect([label("Full Name", 100), span("Full Name", y=100)], POLICY), "NAME"
    )


def test_policy_filters_classes() -> None:
    f = detect([span("alice@example.invalid +1 415 555 0142")], {"EMAIL": "hide_use"})
    assert {x.pii_class for x in f} == {"EMAIL"}


def test_dedupe_same_value_across_spans_collects_all_boxes() -> None:
    a = span("alice@example.invalid", y=100)
    b = span("alice@example.invalid", y=300)
    f = by_class(detect([a, b], POLICY), "EMAIL")
    assert len(f) == 1
    assert f[0].boxes == (a.box, b.box)


def test_sub_box_estimation_for_substring() -> None:
    text = "Card: 4242 4242 4242 4242 end"
    s = TextSpan(text=text, box=Box(100, 50, 290, 18))  # 10px per char
    f = by_class(detect([s], POLICY), "CARD_NUMBER")[0]
    (box,) = f.boxes
    start, end = text.index("4242"), text.index(" end")
    assert box.y == 50 and box.h == 18
    assert box.x <= 100 + 10 * start <= box.x + 10  # starts near char offset, padded outward
    assert box.x + box.w >= 100 + 10 * end - 1
    assert box.x >= 100 and box.x + box.w <= 390
    assert box.w < 290  # not the whole span


def test_input_span_uses_whole_box() -> None:
    s = span("alice@example.invalid", w=600, field_id="email", input_type="text")
    f = by_class(detect([s], POLICY), "EMAIL")[0]
    assert f.boxes == (s.box,)
    assert f.field_id == "email"


def test_no_overlapping_claims_between_detectors() -> None:
    # The IBAN digits must not also be reported as a PHONE / CARD.
    f = detect([span("DE89 3704 0044 0532 0130 00")], POLICY)
    assert {x.pii_class for x in f} == {"BANK_ACCOUNT"}
    f2 = detect([span("078-05-1120")], POLICY)
    assert {x.pii_class for x in f2} == {"SSN"}


# --- paint --------------------------------------------------------------------------------------


def _blank_png(w: int = 200, h: int = 80) -> bytes:
    img = Image.new("RGB", (w, h), (255, 255, 255))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_paint_masks_region_dark_and_keeps_size() -> None:
    png = _blank_png()
    masks = [
        Mask(Box(20, 20, 100, 18), "EMAIL_1_abcd", "EMAIL"),
        Mask(Box(20, 50, 60, 18), None, "SSN"),
    ]
    out = paint(png, masks)
    assert out[:8] == b"\x89PNG\r\n\x1a\n"
    img = Image.open(io.BytesIO(out)).convert("RGB")
    assert img.size == (200, 80)
    # expanded corners are opaque dark
    assert img.getpixel((18, 18)) == MASK_FILL
    assert img.getpixel((121, 39)) == MASK_FILL
    assert img.getpixel((18, 48)) == MASK_FILL
    # outside the masks is untouched
    assert img.getpixel((5, 5)) == (255, 255, 255)
    assert img.getpixel((150, 60)) == (255, 255, 255)
    # nothing inside either mask is still white
    for x in range(18, 122):
        for y in range(18, 40):
            assert img.getpixel((x, y)) != (255, 255, 255)
    for x in range(18, 82):
        for y in range(48, 70):
            assert img.getpixel((x, y)) != (255, 255, 255)
    # token chip has a light pill inside the first mask; blocked mask has no light pixels
    chip_pixels = {img.getpixel((x, 29)) for x in range(24, 116)}
    assert any(p[0] > 200 for p in chip_pixels)
    blocked_pixels = {img.getpixel((x, y)) for x in range(18, 82) for y in range(48, 70)}
    assert all(p[1] < 200 for p in blocked_pixels)


def test_paint_handles_tiny_and_offscreen_boxes() -> None:
    png = _blank_png()
    masks = [Mask(Box(2, 2, 4, 3), "X_1_abcd", "NAME"), Mask(Box(500, 500, 10, 10), None, "SSN")]
    out = paint(png, masks)
    img = Image.open(io.BytesIO(out)).convert("RGB")
    assert img.size == (200, 80)
    assert img.getpixel((0, 0)) == MASK_FILL


# --- redact / scrub -----------------------------------------------------------------------------


def _snapshot(spans: list[TextSpan]) -> Snapshot:
    return Snapshot(
        url="file:///x.html",
        origin="file://",
        title="t",
        width=800,
        height=200,
        png=_blank_png(800, 200),
        spans=spans,
        fields=[],
        focused_field_id=None,
    )


def test_redact_builds_masks_manifest_and_hash() -> None:
    spans = [
        label("Email", 20),
        span("alice@example.invalid", y=20),
        label("SSN", 60),
        span("078-05-1120", y=60),
        span("hunter2", y=100, field_id="pw", input_type="password"),
    ]
    vault = Vault(POLICY, "abcd")
    frame, findings = redact(_snapshot(spans), vault, POLICY)
    classes = {f.pii_class for f in findings}
    assert classes == {"EMAIL", "SSN", "PASSWORD"}
    assert frame.png != _blank_png(800, 200)
    assert len(frame.sha256) == 64
    assert {m.pii_class: m.token for m in frame.masks} == {
        "EMAIL": "EMAIL_1_abcd",
        "SSN": None,
        "PASSWORD": None,
    }
    assert frame.manifest == [{"token": "EMAIL_1_abcd", "class": "EMAIL", "level": "hide_use"}]
    blob = repr(frame.manifest) + repr(frame.masks)
    for f in findings:
        assert f.value not in blob
    assert vault.resolve("EMAIL_1_abcd") == "alice@example.invalid"
    assert vault.blocked_values == {"078-05-1120", "hunter2"}


def test_scrub_text_longest_first_and_blocked() -> None:
    vault = Vault(POLICY, "abcd")
    vault.issue("NAME", "Alice")
    vault.issue("EMAIL", "alice@example.invalid")
    vault.issue("PASSWORD", "hunter2")
    text = "Alice <alice@example.invalid> pw hunter2, again Alice"
    out, hits = scrub_text(text, vault)
    assert out == f"NAME_1_abcd <EMAIL_1_abcd> pw {BLOCKED_LITERAL}, again NAME_1_abcd"
    assert hits == 4
    assert not vault.contains_value(out)
    assert scrub_text("", vault) == ("", 0)
    assert scrub_text("nothing", vault) == ("nothing", 0)
