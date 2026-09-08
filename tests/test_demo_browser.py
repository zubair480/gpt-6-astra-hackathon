"""Integration test: headless Chromium over test-pages/account.html, snapshot, redact.

Skips cleanly when Playwright or its Chromium build is not installed.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from PIL import Image, ImageChops

from plva_agent_demo.browser import VIEWPORT_H, VIEWPORT_W, Browser
from plva_agent_demo.redact import MASK_FILL, redact
from plva_agent_demo.types import DEFAULT_POLICY, Box, Finding, Level, RedactedFrame, Snapshot
from plva_agent_demo.vault import Vault

ROOT = Path(__file__).resolve().parents[1]
PAGE_URL = (ROOT / "test-pages" / "account.html").as_uri()
POLICY: dict[str, Level] = dict(DEFAULT_POLICY)

EXPECTED: dict[str, str] = {
    "EMAIL": "alice.example@example.invalid",
    "PHONE": "+1 415 555 0142",
    "CARD_NUMBER": "4242 4242 4242 4242",
    "SSN": "078-05-1120",
    "BANK_ACCOUNT": "DE89 3704 0044 0532 0130 00",
    "API_KEY": "sk-live-a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
    "SECRET": "whsec_9f8e7d6c5b4a3f2e1d0c9b8a7f6e5d4c",
    "AUTH_TOKEN": "eyJhbGciOiJIUzI1NiJ9.synthetic.token-not-real",
    "PASSWORD": "hunter2-synthetic",
}


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    try:
        b = Browser().__enter__()
    except Exception as exc:
        pytest.skip(f"playwright chromium unavailable: {type(exc).__name__}")
    try:
        yield b
    finally:
        b.close()


@pytest.fixture(scope="module")
def snapshots(browser: Browser) -> list[Snapshot]:
    """Top of page + scrolled to the bottom: the page is taller than one viewport."""
    browser.navigate(PAGE_URL)
    top = browser.snapshot()
    browser.scroll(VIEWPORT_H)
    bottom = browser.snapshot()
    return [top, bottom]


def _all_findings(
    snaps: list[Snapshot], vault: Vault
) -> tuple[list[Finding], list[tuple[Snapshot, RedactedFrame]]]:
    findings: list[Finding] = []
    frames: list[tuple[Snapshot, RedactedFrame]] = []
    for snap in snaps:
        frame, found = redact(snap, vault, POLICY)
        findings.extend(found)
        frames.append((snap, frame))
    return findings, frames


def test_navigate_rejects_non_http_file_schemes(browser: Browser) -> None:
    with pytest.raises(ValueError):
        browser.navigate("javascript:alert(1)")
    with pytest.raises(ValueError):
        browser.navigate("ftp://example.invalid/x")
    with pytest.raises(ValueError):
        browser.navigate("data:text/html,<b>x</b>")


def test_snapshot_shape(snapshots: list[Snapshot]) -> None:
    top = snapshots[0]
    assert top.url == PAGE_URL
    assert top.origin == "file://"
    assert top.title == "Acme Cloud · Account settings"
    assert (top.width, top.height) == (VIEWPORT_W, VIEWPORT_H)
    img = Image.open(io.BytesIO(top.png))
    assert img.size == (VIEWPORT_W, VIEWPORT_H)  # DSF 1: CSS px == screenshot px
    for s in top.spans:
        assert 0 <= s.box.x < VIEWPORT_W and 0 <= s.box.y < VIEWPORT_H
        assert s.box.x + s.box.w <= VIEWPORT_W + 0.01 and s.box.y + s.box.h <= VIEWPORT_H + 0.01
        assert s.box.w > 0 and s.box.h > 0


def test_spans_include_email_and_password_value(snapshots: list[Snapshot]) -> None:
    texts = {s.text for snap in snapshots for s in snap.spans}
    assert EXPECTED["EMAIL"] in texts
    pw = [s for snap in snapshots for s in snap.spans if s.text == EXPECTED["PASSWORD"]]
    assert pw, "password input value must be captured as a span"
    assert all(s.input_type == "password" and s.field_id == "current-password" for s in pw)
    # visible text-input value is captured too
    dn = [s for snap in snapshots for s in snap.spans if s.field_id == "display-name"]
    assert dn and dn[0].text == "alice_e" and dn[0].input_type == "text"


def test_fields_and_labels(snapshots: list[Snapshot]) -> None:
    fields = {f.field_id: f for snap in snapshots for f in snap.fields}
    assert {"api-key-input", "display-name", "support-message", "current-password"} <= set(fields)
    assert fields["display-name"].label == "Display name"
    assert fields["display-name"].input_type == "text"
    assert fields["api-key-input"].label == "Paste your Acme API key to connect"
    assert fields["support-message"].input_type == "textarea"
    assert fields["current-password"].input_type == "password"
    assert fields["current-password"].label == "Current password"
    assert not any(f.focused for f in fields.values())
    assert all(snap.focused_field_id is None for snap in snapshots)


def test_redact_finds_every_expected_class(snapshots: list[Snapshot]) -> None:
    vault = Vault(POLICY, "abcd")
    findings, frames = _all_findings(snapshots, vault)
    found = {(f.pii_class, f.value) for f in findings}
    for cls, value in EXPECTED.items():
        assert (cls, value) in found, f"missing {cls}"
    assert ("CVC", "123") in found
    assert ("DOB", "1990-04-12") in found
    assert ("ADDRESS", "742 Evergreen Terrace, Springfield, OR 97477") in found
    assert {"Alice Example", "Charlie Example", "Bob Example", "Dana Example"} <= {
        f.value for f in findings if f.pii_class == "NAME"
    }
    assert {f.value for f in findings if f.pii_class == "EMAIL"} >= {
        "charlie@example.invalid",
        "bob@example.invalid",
        "dana@example.invalid",
    }

    for snap, frame in frames:
        assert frame.png != snap.png
        assert len(frame.sha256) == 64
        assert Image.open(io.BytesIO(frame.png)).size == (VIEWPORT_W, VIEWPORT_H)

    # blocked classes: mask token None, no manifest entry; others carry tokens
    all_masks = [m for _snap, frame in frames for m in frame.masks]
    manifest = [e for _snap, frame in frames for e in frame.manifest]
    for m in all_masks:
        if POLICY[m.pii_class] == "blocked":
            assert m.token is None
        else:
            assert m.token is not None and m.token.endswith("_abcd")
    manifest_classes = {e["class"] for e in manifest}
    assert manifest_classes == {"EMAIL", "PHONE", "ADDRESS", "DOB", "API_KEY", "AUTH_TOKEN", "NAME"}
    assert all(set(e) == {"token", "class", "level"} for e in manifest)
    for _snap, frame in frames:  # tokens unique within a frame; shared across frames by design
        assert len({e["token"] for e in frame.manifest}) == len(frame.manifest)
    # manifest and masks carry no values
    blob = repr(manifest) + repr(all_masks)
    for f in findings:
        assert f.value not in blob


def _covered(box: Box, masks: list[Box]) -> bool:
    return any(
        m.x <= box.x + 0.01
        and m.y <= box.y + 0.01
        and m.x + m.w >= box.x + box.w - 0.01
        and m.y + m.h >= box.y + box.h - 0.01
        for m in masks
    )


def test_masks_cover_spans_and_pixels_are_painted(snapshots: list[Snapshot]) -> None:
    vault = Vault(POLICY, "abcd")
    for snap in snapshots:
        frame, findings = redact(snap, vault, POLICY)
        raw = Image.open(io.BytesIO(snap.png)).convert("RGB")
        red = Image.open(io.BytesIO(frame.png)).convert("RGB")
        mask_boxes = [m.box for m in frame.masks]
        for f in findings:
            # every span that IS the value (whole-span match) is fully covered by a mask
            for s in snap.spans:
                if s.text == f.value:
                    assert _covered(s.box, mask_boxes), (f.pii_class, s.box)
            for box in f.boxes:
                x0, y0 = int(box.x) - 2, int(box.y) - 2
                x1, y1 = int(box.x + box.w + 0.999) + 1, int(box.y + box.h + 0.999) + 1
                x0, y0 = max(0, x0), max(0, y0)
                x1, y1 = min(VIEWPORT_W - 1, x1), min(VIEWPORT_H - 1, y1)
                # expanded corners are opaque dark
                assert red.getpixel((x0, y0)) == MASK_FILL, f.pii_class
                assert red.getpixel((x1, y1)) == MASK_FILL, f.pii_class
                # and almost no pixel inside survives unchanged from the raw frame
                crop = (int(box.x), int(box.y), int(box.x + box.w), int(box.y + box.h))
                diff = ImageChops.difference(raw.crop(crop), red.crop(crop)).convert("L")
                hist = diff.histogram()
                total, unchanged = sum(hist), hist[0]
                assert total > 0 and unchanged / total < 0.05, f.pii_class


def test_click_type_press_scroll(browser: Browser) -> None:
    browser.navigate(PAGE_URL)
    snap = browser.snapshot()
    field = next(f for f in snap.fields if f.field_id == "display-name")
    browser.click(field.box.x + 10, field.box.y + field.box.h / 2)
    browser.press("ArrowRight")  # End would scroll the document in headless Chromium
    browser.type_text("_x")
    after = browser.snapshot()
    assert after.focused_field_id == "display-name"
    assert next(f for f in after.fields if f.field_id == "display-name").focused
    val = next(s for s in after.spans if s.field_id == "display-name")
    # click in the left padding puts the caret at 0, ArrowRight moves it to 1, then "_x" is typed
    assert val.text == "a_xlice_e"
    browser.scroll(400)
    scrolled = browser.snapshot()
    assert any(s.text == "Team members" for s in scrolled.spans)
    assert (
        next(s for s in scrolled.spans if s.text == "Billing").box.y
        < next(s for s in snap.spans if s.text == "Billing").box.y
    )
    browser.wait_settled()
