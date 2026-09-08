"""Deterministic local classification of OCR regions, never DOM or expected data.

Names require a visible label/greeting. Addresses support English street suffixes
and labelled multiline blocks. Whole OCR regions are masked deliberately: character
coordinates estimated from text length would expose proportional-font edge pixels.
"""
from __future__ import annotations

import re

EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\w)(?:\+\d{1,3}[ .-]?)?(?:\(\d{2,4}\)|\d{3})[ .-]\d{3}[ .-]\d{4}(?!\d)|(?<!\w)\+\d{10,15}(?!\d)")
SECRET = re.compile(r"\b(?:sk[-_]|gh[pousr]_|github_pat_|AKIA|AIza)[A-Za-z0-9_-]{8,}\b|\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
LABEL = re.compile(r"^(?P<label>(?:full |first |last |customer |recipient |account holder )?name|recipient|contact name|(?:shipping |billing |delivery |home |street )?address|deliver to|ship to|password|passcode|api key|access token|secret|email(?: address)?|phone(?: number)?|mobile(?: number)?|tel(?:ephone)?)(?=[:：\s]|$)\s*[:：]?\s*(?P<value>.*)$", re.I)
STREET = re.compile(r"\b\d{1,6}\s+[\w .'-]+\s(?:street|st|avenue|ave|road|rd|lane|ln|drive|dr|boulevard|blvd|court|ct|way|place|pl|terrace|terrace|trail|parkway|pkwy)\b", re.I)
CITY_POSTAL = re.compile(r"(?:\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b|\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b|\b[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}\b)", re.I)
GREETING = re.compile(r"^(?:hello|hi|welcome(?: back)?)[,!]?\s+([\w'’.-]+(?:\s+[\w'’.-]+){0,3})$", re.I)


def _kind(label):
    label = label.lower()
    if label in {"password", "passcode", "api key", "access token", "secret"}:
        return "SECRET"
    if "address" in label and "email" not in label or label in {"deliver to", "ship to"}:
        return "ADDRESS"
    if "email" in label:
        return "EMAIL"
    if label.startswith(("phone", "mobile", "tel")):
        return "PHONE"
    return "NAME"


def classify_regions(regions: list[dict], known_values: list[dict] | None = None) -> list[dict]:
    """Return findings in screenshot pixels; known_values must be local discoveries.

    Each known value is {kind, value}; no provisioning of expected fixture values
    belongs in this API. Failures and invalid coordinates propagate to the caller.
    """
    rows = sorted((dict(r, text=str(r["text"]).strip()) for r in regions if str(r["text"]).strip()), key=lambda r: (r["y"], r["x"]))
    found, seen = [], set()

    def add(kind, value, selected, source):
        value = value.strip(" :：\t\n")
        if not value:
            return
        left = min(r["x"] for r in selected)
        top = min(r["y"] for r in selected)
        right = max(r["x"] + r["width"] for r in selected)
        bottom = max(r["y"] + r["height"] for r in selected)
        key = (kind, value, left, top, right, bottom)
        if key in seen:
            return
        seen.add(key)
        found.append(dict(kind=kind, value=value, label=kind.title(), x=left, y=top,
                          width=right-left, height=bottom-top,
                          confidence=min(float(r.get("confidence", 1.0)) for r in selected), source=source))

    def below(row, limit=5):
        candidates = [r for r in rows if r is not row and r["y"] >= row["y"] + row["height"] * .5
                      and abs(r["x"] - row["x"]) <= max(32, row["height"] * 2)]
        result, edge = [], row["y"] + row["height"]
        for r in candidates:
            if r["y"] - edge > max(36, row["height"] * 2.8) or len(result) >= limit:
                break
            if LABEL.match(r["text"]):
                break
            result.append(r)
            edge = r["y"] + r["height"]
        return result

    for row in rows:
        text = row["text"]
        for kind, pattern in (("EMAIL", EMAIL), ("PHONE", PHONE), ("SECRET", SECRET)):
            for match in pattern.finditer(text):
                add(kind, match.group(), [row], "local-pattern")
        for known in known_values or []:
            value = known["value"]
            # Multiline address OCR often returns separate regions on later pages.
            fragments = [value] + [v.strip() for v in value.splitlines() if len(v.strip()) >= 4]
            # OCR inserts/removes spaces when the same text is zoomed or moved.
            compact_text = re.sub(r"\s+", "", text).casefold()
            if any(re.sub(r"\s+", "", fragment).casefold() in compact_text for fragment in fragments):
                add(known["kind"], value, [row], "local-vault")
        greeting = GREETING.fullmatch(text)
        if greeting and greeting[1].lower() not in {"there", "guest", "sign in"}:
            add("NAME", greeting[1], [row], "visible-greeting")
        match = LABEL.match(text)
        if match:
            kind, value = _kind(match["label"]), match["value"]
            selected = [row] if value else []
            following = below(row)
            if not value:
                # Side-by-side label/value layouts use a separate OCR region.
                right = [r for r in rows if r is not row and r["x"] >= row["x"] + row["width"]
                         and abs(r["y"] - row["y"]) <= max(row["height"], r["height"]) * .5
                         and r["x"] - row["x"] - row["width"] <= 240 and not LABEL.match(r["text"])]
                if right:
                    selected = [min(right, key=lambda r: r["x"])]
                elif following:
                    selected = [following.pop(0)]
                value = selected[0]["text"] if selected else ""
            if kind == "ADDRESS" and selected:
                # Include a recipient and street/city lines, stopping at postal code.
                address_rows = below(selected[-1], limit=4)
                for next_row in address_rows:
                    if CITY_POSTAL.search(value):
                        break
                    if len(value.splitlines()) >= 4:
                        break
                    selected.append(next_row)
                    value += "\n" + next_row["text"]
                add(kind, value, selected, "visible-label")
            elif selected:
                add(kind, value, selected, "visible-label")
        if STREET.search(text):
            selected, value = [row], text
            for next_row in below(row, limit=2):
                if CITY_POSTAL.search(next_row["text"]) or re.match(r"^(?:apt|suite|unit|#)\s*\w", next_row["text"], re.I):
                    selected.append(next_row)
                    value += "\n" + next_row["text"]
                else:
                    break
            add("ADDRESS", value, selected, "local-street-pattern")
    return found


def scrub_patterns(text: str) -> str:
    """Scrub structured data and explicitly labelled values in outbound text."""
    for kind, pattern in (("EMAIL", EMAIL), ("PHONE", PHONE), ("SECRET", SECRET)):
        text = pattern.sub(f"[{kind}_REDACTED]", text)
    lines = []
    for line in text.splitlines(keepends=True):
        newline = "\n" if line.endswith("\n") else ""
        match = LABEL.match(line.strip())
        if match and match["value"] and not re.fullmatch(r"\[[A-Z_]+(?:_\d+)?\]", match["value"]):
            line = f"{match['label']}: [{_kind(match['label'])}_REDACTED]" + newline
        else:
            line = STREET.sub("[ADDRESS_REDACTED]", line)
        lines.append(line)
    return "".join(lines)
