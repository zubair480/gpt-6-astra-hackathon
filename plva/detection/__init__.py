"""Local screenshot privacy detection. Raw OCR and values never leave this module."""

from __future__ import annotations

import threading


class DetectionError(RuntimeError):
    """Local inference failed; callers must stop observation delivery."""


class ScreenshotDetector:
    """Read only PNG pixels and remember discoveries for this detector session.

    The optional OCR adapter exists for testing. Production uses bundled local
    ONNX models on CPU; no DOM, website metadata, or remote inference is used.
    """

    name = "RapidOCR CPU + local contextual rules"

    def __init__(self, *, ocr=None):
        if ocr is None:
            from .ocr import LocalOCR
            ocr = LocalOCR()
        self._ocr = ocr
        self._known: dict[str, str] = {}
        self._lock = threading.Lock()

    def detect(self, png: bytes) -> list[dict]:
        from .classify import classify_regions

        try:
            with self._lock:
                regions = self._ocr.recognize(png)
                findings = classify_regions(regions, known_values=[
                    {"kind": kind, "value": value}
                    for value, kind in self._known.items()])
                unique = {}
                for finding in findings:
                    key = tuple(finding[k] for k in
                                ("kind", "value", "x", "y", "width", "height"))
                    unique[key] = finding
                    value, kind = finding["value"], finding["kind"]
                    if self._known.get(value) != "SECRET":
                        self._known[value] = kind
                return list(unique.values())
        except Exception:
            # Errors may contain recognized private text. Keep UI errors generic.
            raise DetectionError("Local screenshot detection failed") from None


__all__ = ["ScreenshotDetector", "DetectionError"]
