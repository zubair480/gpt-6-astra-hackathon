"""Local, session-scoped privacy primitives for the PLVA hackathon demo."""

from __future__ import annotations

import io
import math
import re

from PIL import Image, ImageDraw, ImageFont


class PrivacyError(ValueError):
    """An observation or action cannot safely pass the demo privacy boundary."""


class PrivacySession:
    """Keep raw values in memory; expose only tokens in observation metadata."""

    KINDS = frozenset({"EMAIL", "NAME", "ADDRESS", "PHONE", "SECRET"})
    TOKEN = re.compile(r"\[[A-Z][A-Z_]*_\d+\]")
    EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
    KEY = re.compile(r"\b(?:sk[-_]|ghp_)[A-Za-z0-9_-]{8,}\b")

    def __init__(self):
        self._tokens: dict[tuple[str, str], str] = {}
        self._values: dict[str, str] = {}
        self._blocked: set[str] = set()
        self._counts: dict[str, int] = {}

    def _register(self, kind: str, value: str) -> str:
        if kind == "SECRET":
            # A later secret classification revokes any earlier usable alias.
            for old_token, old_value in list(self._values.items()):
                if old_value == value:
                    self._blocked.add(old_token)
                    del self._values[old_token]
        key = (kind, value)
        if key not in self._tokens:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            token = f"[{kind}_{self._counts[kind]}]"
            self._tokens[key] = token
            if kind == "SECRET" or ("SECRET", value) in self._tokens:
                self._blocked.add(token)
            else:
                self._values[token] = value
        return self._tokens[key]

    def protect(self, png: bytes, findings: list[dict]) -> dict:
        """Return a fresh PNG plus value-free metadata, or raise PrivacyError.

        Coordinates must use screenshot pixels. Detection belongs to the caller;
        this method deliberately makes no claim to find unknown private content.
        """
        try:
            with Image.open(io.BytesIO(png)) as source:
                source.load()
                frame = source.convert("RGB")
            checked = []
            for finding in findings:
                kind, value = finding["kind"], finding["value"]
                if kind not in self.KINDS or not isinstance(value, str) or not value:
                    raise PrivacyError("Invalid private-field finding")
                x, y, width, height = (
                    float(finding[k]) for k in ("x", "y", "width", "height")
                )
                if not all(math.isfinite(v) for v in (x, y, width, height)):
                    raise PrivacyError("Invalid mask coordinates")
                if width <= 0 or height <= 0:
                    raise PrivacyError("Invalid mask dimensions")
                # Round outwards so fractional coordinates never expose edge pixels.
                box = (max(0, math.floor(x)), max(0, math.floor(y)),
                       min(frame.width, math.ceil(x + width)),
                       min(frame.height, math.ceil(y + height)))
                if box[0] >= box[2] or box[1] >= box[3]:
                    raise PrivacyError("Private field is outside captured frame")
                checked.append((kind, value, box))

            manifest, masks = [], []
            seen = set()
            for kind, value, box in checked:
                token = self._register(kind, value)
                # Generic labels prevent a caller-supplied label leaking raw values.
                if token not in seen:
                    manifest.append({"token": token, "kind": kind, "label": kind.title()})
                    seen.add(token)
                left, top, right, bottom = box
                mask = Image.new("RGB", (right - left, bottom - top), "#182435")
                draw = ImageDraw.Draw(mask)
                font_size = min(13, max(1, mask.height - 4))
                font = ImageFont.load_default(size=font_size)
                while font_size > 1 and draw.textlength(token, font=font) > mask.width - 6:
                    font_size -= 1
                    font = ImageFont.load_default(size=font_size)
                draw.text((3, max(0, (mask.height - font_size - 2) // 2)), token,
                          fill="#8ee9d4", font=font)
                # Rendering into the mask itself clips labels to protected bounds.
                frame.paste(mask, (left, top))
                masks.append({"token": token, "kind": kind,
                              "x": left, "y": top,
                              "width": right - left, "height": bottom - top})
            output = io.BytesIO()
            frame.save(output, format="PNG")
            return {"png": output.getvalue(), "manifest": manifest,
                    "masks": masks, "count": len(masks)}
        except PrivacyError:
            raise
        except Exception:
            # Do not reflect source text, decoder details, or raw bytes into audits.
            raise PrivacyError("Observation protection failed") from None

    def resolve(self, text: str) -> str:
        """Resolve issued non-secret tokens. Call only after action authorization."""
        def replace(match):
            token = match.group(0)
            if token in self._blocked:
                raise PrivacyError("Blocked secret token cannot be used")
            if token not in self._values:
                raise PrivacyError("Unknown private token")
            return self._values[token]
        return self.TOKEN.sub(replace, text)

    def scrub(self, text: str) -> str:
        """Remove known values from history, including non-resolvable secrets."""
        replacements = {}
        for (kind, value), token in self._tokens.items():
            # A value classified as a secret must not be presented as usable.
            if value not in replacements or kind == "SECRET":
                replacements[value] = token
        if replacements:
            pattern = re.compile("|".join(re.escape(v) for v in
                                         sorted(replacements, key=len, reverse=True)))
            text = pattern.sub(lambda match: replacements[match.group(0)], text)
        from plva.detection.classify import scrub_patterns
        return scrub_patterns(text)

    def local_known_values(self) -> list[dict]:
        """Copy discovered values for LOCAL OCR matching only; never serialize/send.

        Includes blocked secrets so later unlabelled occurrences remain masked.
        Returned dictionaries are copies and cannot mutate the in-memory vault.
        """
        return [{"kind": kind, "value": value} for kind, value in self._tokens]
