"""Pixel-only OCR using RapidOCR 1.4.4 and a verified English recognizer.

Install ``rapidocr-onnxruntime==1.4.4`` then run
``python -m plva.detection.provision`` once. The wheel supplies the detector and
angle classifier; a pinned English model improves spacing in recognized values.
Construction and inference do not fetch models or transmit screenshot content.
No GPU, external OCR service, browser metadata or expected-value list is used.
"""

from __future__ import annotations

import io
import math
import threading

from PIL import Image


class LocalOCR:
    """Return whole text-line regions in original screenshot pixel coordinates.

    Text recognition is fallible, especially for small, low contrast or obscured
    text. A successful empty result means no text was recognized, not proof that
    a screenshot has no private data. Initialization/inference errors propagate.
    """

    name = "RapidOCR / PaddleOCR v4 / ONNX Runtime CPU"

    def __init__(self, *, text_score: float = 0.35, threads: int = 2):
        if not 0 <= text_score <= 1:
            raise ValueError("text_score must be between zero and one")
        if threads < 1:
            raise ValueError("threads must be positive")
        try:
            from rapidocr_onnxruntime import RapidOCR
        except ImportError as exc:
            raise RuntimeError(
                "Local OCR is unavailable. Install rapidocr-onnxruntime==1.4.4 "
                "with its bundled ONNX models before starting detection."
            ) from exc
        from .provision import model_paths
        recognizer, dictionary = model_paths()
        self._engine = RapidOCR(
            rec_model_path=recognizer,
            rec_keys_path=dictionary,
            text_score=text_score,
            intra_op_num_threads=threads,
            inter_op_num_threads=1,
            det_use_cuda=False,
            det_use_dml=False,
            cls_use_cuda=False,
            cls_use_dml=False,
            rec_use_cuda=False,
            rec_use_dml=False,
            max_side_len=4096,
            det_limit_side_len=1280,
            det_limit_type="max",
        )
        self._lock = threading.Lock()

    def recognize(self, png: bytes) -> list[dict]:
        import numpy as np

        if not isinstance(png, bytes) or not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("OCR input must be PNG bytes")
        with Image.open(io.BytesIO(png)) as image:
            image.load()
            width, height = image.size
            # Composite transparency over white, matching an ordinary page.
            rgba = image.convert("RGBA")
            background = Image.new("RGBA", image.size, "white")
            background.alpha_composite(rgba)
            rgb = background.convert("RGB")
            pixels = np.asarray(rgb)[:, :, ::-1].copy()  # RapidOCR takes BGR.
        # RapidOCR updates preprocessing state per call; serialize shared use.
        with self._lock:
            result, _ = self._engine(pixels)
        regions = []
        for points, text, confidence in result or []:
            if not text or not str(text).strip():
                continue
            xs = [float(point[0]) for point in points]
            ys = [float(point[1]) for point in points]
            if not all(math.isfinite(v) for v in xs + ys + [float(confidence)]):
                raise RuntimeError("OCR returned non-finite region coordinates")
            # Include antialiasing and glyph strokes just outside detector boxes.
            x = max(0, min(width, math.floor(min(xs)) - 3))
            y = max(0, min(height, math.floor(min(ys)) - 3))
            right = max(x, min(width, math.ceil(max(xs)) + 3))
            bottom = max(y, min(height, math.ceil(max(ys)) + 3))
            if right <= x or bottom <= y:
                raise RuntimeError("OCR returned an empty text region")
            regions.append({
                "text": str(text).strip(), "x": x, "y": y,
                "width": right - x, "height": bottom - y,
                "confidence": float(confidence),
            })
        return regions
