"""Screenshot redaction: deterministic PII detectors over text spans, mask painting, scrubbing.

Pure functions, no browser dependency. Nothing in this module logs or prints span text.
"""

from __future__ import annotations

import hashlib
import io
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from .types import Box, Finding, Level, Mask, PiiClass, RedactedFrame, Snapshot, TextSpan
from .vault import Vault

MASK_FILL: Final = (17, 17, 17)
CHIP_FILL: Final = (229, 231, 235)
CHIP_TEXT: Final = (17, 17, 17)
HATCH_FILL: Final = (60, 60, 60)
BLOCKED_TEXT: Final = (248, 113, 113)
MASK_PAD: Final = 2
BLOCKED_LITERAL: Final = "«BLOCKED»"

# --- regexes -----------------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9-])")
_PHONE_RE = re.compile(
    r"(?<![\w.])(?:\+\d{1,3}[\s.-]?)?(?:\(\d{2,4}\)[\s.-]?|\d{2,4}[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}(?![\w-])"
)
_CARD_RE = re.compile(r"(?<![\dA-Za-z])(?:\d[ -]?){12,18}\d(?![\dA-Za-z])")
_SSN_RE = re.compile(r"(?<![\d-])\d{3}-\d{2}-\d{4}(?![\d-])")
_IBAN_RE = re.compile(r"(?<![A-Z0-9])[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}(?![A-Z0-9])")
_CVC_INLINE_RE = re.compile(r"(?i)\bCV[CV]2?\s*[:#=]?\s*(\d{3,4})(?!\d)")
_CVC_LOOSE_RE = re.compile(r"(?<![\d./-])\d{3,4}(?![\d./-])")
_DOB_RE = re.compile(r"(?<![\d/-])(?:\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\.\d{1,2}\.\d{4})(?![\d/-])")
_DOB_CONTEXT_RE = re.compile(r"(?i)birth|\bdob\b|\bborn\b")
_STREET_SUFFIX = (
    "Terrace|Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way|Place|Pl|"
    "Square|Sq|Highway|Hwy|Parkway|Pkwy|Circle|Cir|Trail|Trl|Crescent|Cres|Close"
)
_ADDRESS_RE = re.compile(
    r"(?<![\d.])\d{1,6}[A-Za-z]?\s+(?:[A-Z][A-Za-z'.-]*\s+){1,4}(?:" + _STREET_SUFFIX + r")\b\.?"
    r"(?:,?\s*(?:Apt|Apartment|Suite|Ste|Unit|Floor|Fl|#)\.?\s*[A-Za-z0-9-]+)?"
    r"(?:,\s*[A-Za-z][A-Za-z.'-]*(?:\s[A-Za-z.'-]+){0,4}){0,3}(?:\s+\d{5}(?:-\d{4})?)?"
)
_API_KEY_RES = [
    re.compile(r"(?<![A-Za-z0-9_-])sk-(?:live-|test-|proj-|ant-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"(?<![A-Za-z0-9])AKIA[0-9A-Z]{16}(?![A-Za-z0-9])"),
    re.compile(r"(?<![A-Za-z0-9_])(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}"),
    re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{22,}"),
    re.compile(r"(?<![A-Za-z0-9_-])xox[abpos]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![0-9A-Za-z_-])"),
    re.compile(r"(?<![A-Za-z0-9_-])(?:pk|rk)_(?:live|test)_[A-Za-z0-9]{16,}"),
]
_SECRET_RES = [
    re.compile(r"(?<![A-Za-z0-9_-])whsec_[A-Za-z0-9]{16,}"),
    re.compile(r"(?<![A-Za-z0-9_-])sk_(?:live|test)_[A-Za-z0-9]{16,}"),
]
_JWT_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:eyJ[A-Za-z0-9_-]{6,}|[A-Za-z0-9_-]{20,})\.[A-Za-z0-9_-]{2,}\.[A-Za-z0-9_-]{2,}"
    r"(?![A-Za-z0-9_.-])"
)
_BEARER_RE = re.compile(r"(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{20,})")
_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----(?:.*?-----END [A-Z ]*PRIVATE KEY-----|.*)", re.DOTALL
)
_GENERIC_BASE62_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{24,}(?![A-Za-z0-9])")
_GENERIC_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9._-])[A-Za-z0-9._-]{20,}(?![A-Za-z0-9._-])")
_KEY_LABEL_RE = re.compile(r"(?i)\b(?:api[\s_-]?key|access[\s_-]?key|secret[\s_-]?key|key)\b")
_SECRET_LABEL_RE = re.compile(r"(?i)\bsecret\b")
_TOKEN_LABEL_RE = re.compile(r"(?i)\btoken\b")
_NAME_LABEL_RE = re.compile(r"(?i)\bname\b")
_NAME_RE = re.compile(
    r"(?<![A-Za-z])[A-Z][a-z]{1,}(?:[-'][A-Z][a-z]+)?"
    r"(?:\s+(?:[A-Z]\.\s+)?[A-Z][a-z]{1,}(?:[-'][A-Z][a-z]+)?){1,2}(?![A-Za-z])"
)

_ROW_TOLERANCE_PX: Final = 40.0


# --- helpers -----------------------------------------------------------------------------------


def luhn_ok(digits: str) -> bool:
    if not digits.isdigit() or len(digits) < 13:
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def iban_ok(iban: str) -> bool:
    compact = iban.replace(" ", "").upper()
    if not (15 <= len(compact) <= 34) or not compact[:2].isalpha() or not compact[2:4].isdigit():
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    return int(numeric) % 97 == 1


def _cy(b: Box) -> float:
    return b.y + b.h / 2.0


def _same_row(a: Box, b: Box) -> bool:
    return (a.y <= _cy(b) <= a.y + a.h) or (b.y <= _cy(a) <= b.y + b.h)


def _near_row(a: Box, b: Box) -> bool:
    return _same_row(a, b) or abs(_cy(a) - _cy(b)) <= _ROW_TOLERANCE_PX


def _x_overlap(a: Box, b: Box) -> float:
    return min(a.x + a.w, b.x + b.w) - max(a.x, b.x)


def _sub_box(span: TextSpan, start: int, end: int) -> Box:
    """Estimate the box of span.text[start:end]; whole box for inputs or full-span matches."""
    n = len(span.text)
    if span.field_id is not None or n == 0 or (start <= 0 and end >= n):
        return span.box
    b = span.box
    cw = b.w / n
    pad = cw * 0.6  # proportional fonts: widen slightly so we err on over-covering
    x0 = max(b.x, b.x + cw * start - pad)
    x1 = min(b.x + b.w, b.x + cw * end + pad)
    return Box(round(x0, 2), b.y, round(x1 - x0, 2), b.h)


@dataclass(slots=True)
class _Hit:
    pii_class: str
    value: str
    span_idx: int
    start: int
    end: int


class _Detector:
    def __init__(self, spans: list[TextSpan]) -> None:
        self.spans = spans
        self.claimed: dict[int, list[tuple[int, int]]] = {}
        self.hits: list[_Hit] = []

    # -- claim bookkeeping ------------------------------------------------------------------

    def _free(self, idx: int, start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in self.claimed.get(idx, []))

    def _add(self, pii_class: str, idx: int, start: int, end: int, value: str | None = None) -> None:
        if start >= end or not self._free(idx, start, end):
            return
        v = value if value is not None else self.spans[idx].text[start:end]
        if not v.strip():
            return
        self.claimed.setdefault(idx, []).append((start, end))
        self.hits.append(_Hit(pii_class, v, idx, start, end))

    def _scan(
        self,
        pii_class: str,
        pattern: re.Pattern[str],
        validate: Callable[[str], bool] | None = None,
        only: Iterable[int] | None = None,
        group: int = 0,
    ) -> None:
        indices = range(len(self.spans)) if only is None else only
        for idx in indices:
            span = self.spans[idx]
            if span.input_type == "password":
                continue
            for m in pattern.finditer(span.text):
                value = m.group(group)
                if validate is not None and not validate(value):
                    continue
                self._add(pii_class, idx, m.start(group), m.end(group), value)

    # -- context ----------------------------------------------------------------------------

    def _row_text(self, idx: int, strict: bool) -> str:
        me = self.spans[idx]
        parts: list[str] = []
        for j, other in enumerate(self.spans):
            if j == idx:
                continue
            ok = _same_row(me.box, other.box) if strict else _near_row(me.box, other.box)
            if ok:
                parts.append(other.text)
        return " ".join(parts)

    def _left_label(self, idx: int) -> str:
        me = self.spans[idx]
        parts: list[str] = []
        for j, other in enumerate(self.spans):
            if j == idx or not _same_row(me.box, other.box):
                continue
            if other.box.x + other.box.w <= me.box.x + 2:
                parts.append(other.text)
        return " ".join(parts)

    def _column_header(self, idx: int) -> str:
        me = self.spans[idx]
        best: tuple[float, str] | None = None
        for j, other in enumerate(self.spans):
            if j == idx or len(other.text) > 24 or _x_overlap(me.box, other.box) <= 0:
                continue
            if other.box.y + other.box.h > me.box.y:
                continue
            if _NAME_LABEL_RE.search(other.text) is None:
                continue
            dist = me.box.y - (other.box.y + other.box.h)
            if best is None or dist < best[0]:
                best = (dist, other.text)
        return best[1] if best else ""

    def _spans_with_context(self, label_re: re.Pattern[str], strict: bool) -> list[int]:
        out: list[int] = []
        for idx, span in enumerate(self.spans):
            if label_re.search(span.text) or label_re.search(self._row_text(idx, strict)):
                out.append(idx)
        return out

    # -- detectors --------------------------------------------------------------------------

    def run(self, policy: dict[str, Level]) -> list[_Hit]:
        want = set(policy)
        # Pass 1: pattern-only detectors, most specific first.
        if "PASSWORD" in want:
            for idx, span in enumerate(self.spans):
                if span.input_type == "password" and span.text:
                    self._add("PASSWORD", idx, 0, len(span.text), span.text)
        if "PRIVATE_KEY" in want:
            self._scan("PRIVATE_KEY", _PRIVATE_KEY_RE)
        if "API_KEY" in want:
            for pat in _API_KEY_RES:
                self._scan("API_KEY", pat)
        if "SECRET" in want:
            for pat in _SECRET_RES:
                self._scan("SECRET", pat)
        if "AUTH_TOKEN" in want:
            self._scan("AUTH_TOKEN", _BEARER_RE, group=1)
            self._scan("AUTH_TOKEN", _JWT_RE, validate=_looks_like_jwt)
        if "EMAIL" in want:
            self._scan("EMAIL", _EMAIL_RE)
        if "CARD_NUMBER" in want:
            self._scan("CARD_NUMBER", _CARD_RE, validate=lambda v: luhn_ok(re.sub(r"[ -]", "", v)))
        if "BANK_ACCOUNT" in want:
            self._scan("BANK_ACCOUNT", _IBAN_RE, validate=iban_ok)
        if "SSN" in want:
            self._scan("SSN", _SSN_RE, validate=_ssn_plausible)
        if "CVC" in want:
            self._detect_cvc()
        if "DOB" in want:
            self._scan("DOB", _DOB_RE, only=self._spans_with_context(_DOB_CONTEXT_RE, strict=False))
        if "ADDRESS" in want:
            self._scan("ADDRESS", _ADDRESS_RE)
        if "PHONE" in want:
            self._scan("PHONE", _PHONE_RE, validate=_phone_plausible)
        # Pass 2: label-driven generic detectors (strict same-row context only).
        if "API_KEY" in want:
            self._scan(
                "API_KEY", _GENERIC_BASE62_RE, only=self._spans_with_context(_KEY_LABEL_RE, True)
            )
        if "SECRET" in want:
            self._scan(
                "SECRET", _GENERIC_TOKEN_RE, only=self._spans_with_context(_SECRET_LABEL_RE, True)
            )
        if "AUTH_TOKEN" in want:
            self._scan(
                "AUTH_TOKEN", _GENERIC_TOKEN_RE, only=self._spans_with_context(_TOKEN_LABEL_RE, True)
            )
        if "NAME" in want:
            self._detect_names()
        return self.hits

    def _detect_cvc(self) -> None:
        for idx, span in enumerate(self.spans):
            if span.input_type == "password":
                continue
            inline = list(_CVC_INLINE_RE.finditer(span.text))
            if inline:
                for m in inline:
                    self._add("CVC", idx, m.start(1), m.end(1))
                continue
            ctx = self._row_text(idx, strict=False)
            if re.search(r"(?i)\bCV[CV]2?\b", ctx) and not re.search(r"(?i)\bCV[CV]2?\b", span.text):
                for m in _CVC_LOOSE_RE.finditer(span.text):
                    self._add("CVC", idx, m.start(), m.end())

    def _detect_names(self) -> None:
        for idx, span in enumerate(self.spans):
            if span.input_type == "password" or span.field_id is not None:
                continue
            if _NAME_RE.fullmatch(span.text.strip()) is None and _NAME_RE.search(span.text) is None:
                continue
            label = self._left_label(idx)
            header = self._column_header(idx)
            if _NAME_LABEL_RE.search(label) is None and not header:
                continue
            for m in _NAME_RE.finditer(span.text):
                if _NAME_LABEL_RE.search(m.group(0)):
                    continue  # the label itself ("Full Name")
                self._add("NAME", idx, m.start(), m.end())


def _looks_like_jwt(value: str) -> bool:
    if value.startswith("eyJ"):
        return True
    parts = value.split(".")
    return all(any(c.isdigit() for c in p) and any(c.isalpha() for c in p) for p in parts)


def _ssn_plausible(value: str) -> bool:
    area, group, serial = value.split("-")
    return area not in {"000", "666"} and group != "00" and serial != "0000"


def _phone_plausible(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    if not 7 <= len(digits) <= 15:
        return False
    if len(set(digits)) == 1:
        return False
    return not re.fullmatch(r"\d{4}[\s.-]\d{2}[\s.-]\d{2}", value)  # ISO date


# --- public API ---------------------------------------------------------------------------------


def detect(spans: list[TextSpan], policy: dict[str, Level]) -> list[Finding]:
    """Run every detector whose class is in ``policy``; one Finding per distinct (class, value)."""
    hits = _Detector(list(spans)).run(policy)
    grouped: dict[tuple[str, str], list[Box]] = {}
    field_ids: dict[tuple[str, str], str | None] = {}
    order: list[tuple[str, str]] = []
    for hit in hits:
        key = (hit.pii_class, hit.value)
        span = spans[hit.span_idx]
        box = _sub_box(span, hit.start, hit.end)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
            field_ids[key] = span.field_id
        if box not in grouped[key]:
            grouped[key].append(box)
        if field_ids[key] is None and span.field_id is not None:
            field_ids[key] = span.field_id
    findings: list[Finding] = []
    for key in order:
        pii_class, value = key
        findings.append(
            Finding(
                pii_class=pii_class,  # type: ignore[arg-type]
                value=value,
                boxes=tuple(grouped[key]),
                field_id=field_ids[key],
            )
        )
    return findings


_FONT_CANDIDATES: Final = (
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "C:/Windows/Fonts/consola.ttf",
)
_font_cache: dict[int, ImageFont.FreeTypeFont | ImageFont.ImageFont] = {}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if size in _font_cache:
        return _font_cache[size]
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont | None = None
    for path in _FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, size)
            break
        except OSError:
            continue
    if font is None:
        try:
            font = ImageFont.load_default(size=size)
        except TypeError:  # pragma: no cover - very old Pillow
            font = ImageFont.load_default()
    _font_cache[size] = font
    return font


def _expanded(box: Box, width: int, height: int) -> tuple[int, int, int, int]:
    x0 = max(0, int(box.x) - MASK_PAD)
    y0 = max(0, int(box.y) - MASK_PAD)
    x1 = min(width, int(box.x + box.w + 0.999) + MASK_PAD)
    y1 = min(height, int(box.y + box.h + 0.999) + MASK_PAD)
    return x0, y0, x1, y1


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int) -> tuple[str, int] | None:
    size = max(8, min(14, max_h - 4))
    while size >= 8:
        font = _font(size)
        l, t, r, b = draw.textbbox((0, 0), text, font=font)
        if r - l <= max_w and b - t <= max_h:
            return text, size
        size -= 1
    font = _font(8)
    clipped = text
    while len(clipped) > 1:
        clipped = clipped[:-1]
        l, t, r, b = draw.textbbox((0, 0), clipped + "…", font=font)
        if r - l <= max_w and b - t <= max_h:
            return clipped + "…", 8
    return None


def _draw_chip(draw: ImageDraw.ImageDraw, rect: tuple[int, int, int, int], token: str) -> None:
    x0, y0, x1, y1 = rect
    px0, py0, px1, py1 = x0 + MASK_PAD, y0 + MASK_PAD, x1 - MASK_PAD, y1 - MASK_PAD
    if px1 - px0 < 12 or py1 - py0 < 7:
        return
    draw.rounded_rectangle((px0, py0, px1, py1), radius=min(6, (py1 - py0) // 2), fill=CHIP_FILL)
    fitted = _fit_text(draw, token, max_w=px1 - px0 - 6, max_h=py1 - py0 - 2)
    if fitted is None:
        return
    text, size = fitted
    font = _font(size)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    tx = px0 + ((px1 - px0) - (r - l)) / 2 - l
    ty = py0 + ((py1 - py0) - (b - t)) / 2 - t
    draw.text((tx, ty), text, font=font, fill=CHIP_TEXT)


def _draw_blocked(img: Image.Image, rect: tuple[int, int, int, int]) -> None:
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return
    tile = Image.new("RGB", (w, h), MASK_FILL)  # hatch on a tile so lines never leave the mask
    tile_draw = ImageDraw.Draw(tile)
    step = 7
    for k in range(-h, w, step):
        tile_draw.line((k, h, k + h, 0), fill=HATCH_FILL, width=1)
    img.paste(tile, (x0, y0))
    draw = ImageDraw.Draw(img)
    if w < 24 or h < 8:
        return
    fitted = _fit_text(draw, "BLOCKED", max_w=w - 6, max_h=h - 2)
    if fitted is None:
        return
    text, size = fitted
    font = _font(size)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    tx = x0 + (w - tw) / 2 - l
    ty = y0 + (h - th) / 2 - t
    draw.rectangle((tx + l - 2, ty + t - 1, tx + r + 2, ty + b + 1), fill=MASK_FILL)
    draw.text((tx, ty), text, font=font, fill=BLOCKED_TEXT)


def paint(png: bytes, masks: list[Mask]) -> bytes:
    """Paint opaque masks (expanded by 2px) with token chips / BLOCKED hatching. Returns PNG."""
    img = Image.open(io.BytesIO(png)).convert("RGB")
    draw = ImageDraw.Draw(img)
    width, height = img.size
    rects = [_expanded(m.box, width, height) for m in masks]
    for x0, y0, x1, y1 in rects:  # first pass: everything opaque
        if x1 > x0 and y1 > y0:
            draw.rectangle((x0, y0, x1 - 1, y1 - 1), fill=MASK_FILL)
    for mask, rect in zip(masks, rects, strict=True):  # second pass: chips (all inside masks)
        x0, y0, x1, y1 = rect
        if x1 <= x0 or y1 <= y0:
            continue
        if mask.token is None:
            _draw_blocked(img, (x0, y0, x1, y1))
        else:
            _draw_chip(draw, rect, mask.token)
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def redact(
    snapshot: Snapshot, vault: Vault, policy: dict[str, Level]
) -> tuple[RedactedFrame, list[Finding]]:
    """Detect PII in the snapshot, issue tokens, paint masks. Returns the outbound frame + findings."""
    findings = detect(snapshot.spans, policy)
    masks: list[Mask] = []
    manifest: list[dict[str, str]] = []
    seen_tokens: set[str] = set()
    for finding in findings:
        token = vault.issue(finding.pii_class, finding.value)
        for box in finding.boxes:
            masks.append(Mask(box=box, token=token, pii_class=finding.pii_class))
        if token is not None and token not in seen_tokens:
            seen_tokens.add(token)
            manifest.append(
                {
                    "token": token,
                    "class": finding.pii_class,
                    "level": policy.get(finding.pii_class, "hide_use"),
                }
            )
    png = paint(snapshot.png, masks)
    frame = RedactedFrame(
        png=png, masks=masks, manifest=manifest, sha256=hashlib.sha256(png).hexdigest()
    )
    return frame, findings


def scrub_text(text: str, vault: Vault) -> tuple[str, int]:
    """Replace every vault value in ``text`` with its token (blocked -> «BLOCKED»). Longest first."""
    if not text:
        return text, 0
    hits = 0
    for value, token in vault.values_longest_first():
        if not value or value not in text:
            continue
        replacement = token if token is not None else BLOCKED_LITERAL
        hits += text.count(value)
        text = text.replace(value, replacement)
    return text, hits


__all__ = [
    "BLOCKED_LITERAL",
    "PiiClass",
    "detect",
    "iban_ok",
    "luhn_ok",
    "paint",
    "redact",
    "scrub_text",
]
