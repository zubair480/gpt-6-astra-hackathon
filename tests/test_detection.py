"""PNG-only regression fixtures, generated at runtime with previously unseen values."""
import io
import json
import os
import unittest
import uuid
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from plva.detection import DetectionError, ScreenshotDetector
from plva.privacy import PrivacySession


def render(lines, size=22, offset=(35, 30)):
    image = Image.new("RGB", (1100, 650), "white")
    draw = ImageDraw.Draw(image)
    font_path = "C:/Windows/Fonts/arial.ttf"
    font = ImageFont.truetype(font_path, size) if os.path.exists(font_path) else ImageFont.truetype("DejaVuSans.ttf", size)
    for i, line in enumerate(lines):
        draw.text((offset[0], offset[1] + i * (size + 18)), line, fill="black", font=font)
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class DetectorTests(unittest.TestCase):
    def test_missing_or_corrupt_models_fail_without_network(self):
        from plva.detection import provision
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(provision, "MODEL_DIR", Path(directory)):
                with self.assertRaisesRegex(RuntimeError, "missing or invalid"):
                    provision.model_paths()
                for name, _, _ in provision.ASSETS:
                    (Path(directory) / name).write_bytes(b"corrupt")
                with self.assertRaisesRegex(RuntimeError, "missing or invalid"):
                    provision.model_paths()

    def test_secret_reclassification_revokes_usable_aliases(self):
        session = PrivacySession()
        png = render([])
        base = dict(value="new-private-passphrase", label="Value", x=5, y=5, width=100, height=30)
        session.protect(png, [dict(base, kind="NAME")])
        session.protect(png, [dict(base, kind="SECRET")])
        from plva.privacy import PrivacyError
        with self.assertRaises(PrivacyError):
            session.resolve("[NAME_1]")

    def test_inference_failure_raises(self):
        class Broken:
            def recognize(self, png):
                raise RuntimeError("private diagnostic")
        with self.assertRaisesRegex(DetectionError, "^Local screenshot detection failed$"):
            ScreenshotDetector(ocr=Broken()).detect(b"anything")

    def test_discovered_name_is_remasked_without_label(self):
        class OCR:
            text = "Name: Nadia Merrow"
            def recognize(self, png):
                return [dict(text=self.text, x=5, y=8, width=170, height=24, confidence=.99)]
        ocr = OCR()
        detector = ScreenshotDetector(ocr=ocr)
        self.assertTrue(any(f["kind"] == "NAME" for f in detector.detect(b"test")))
        ocr.text = "Nadia Merrow"
        self.assertTrue(any(f["kind"] == "NAME" for f in detector.detect(b"test")))


@unittest.skipUnless(os.environ.get("PLVA_TEST_OCR") == "1", "set PLVA_TEST_OCR=1 for actual CPU model inference")
class RealOCRTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.detector = ScreenshotDetector()

    def test_fresh_pixels_multiple_layouts_and_masks(self):
        for font_size, offset in [(22, (35, 30)), (16, (240, 165)), (28, (80, 75))]:
            with self.subTest(font_size=font_size):
                email = "contact" + uuid.uuid4().hex[:6] + "@example.org"
                png = render(["Account contact", "Name: Nadia Merrow", "Email: " + email,
                              "Phone: (415) 555-0198", "Shipping address:",
                              "742 Juniper Lane", "Portland, OR 97205",
                              "API key: sk-demo9x7a6b5c4d3e2f1g"], font_size, offset)
                findings = self.detector.detect(png)
                kinds = {f["kind"] for f in findings}
                self.assertTrue({"EMAIL", "PHONE", "NAME", "ADDRESS", "SECRET"} <= kinds, findings)
                self.assertTrue(any(email.lower() == f["value"].lower() for f in findings), findings)
                privacy = PrivacySession()
                result = privacy.protect(png, findings)
                protected = Image.open(io.BytesIO(result["png"]))
                # Compare each mask with protection of wholly different pixels.
                alt = io.BytesIO()
                Image.new("RGB", protected.size, "red").save(alt, "PNG")
                second = Image.open(io.BytesIO(privacy.protect(alt.getvalue(), findings)["png"]))
                for mask in result["masks"]:
                    box = (mask["x"], mask["y"], mask["x"] + mask["width"], mask["y"] + mask["height"])
                    self.assertEqual(protected.crop(box).tobytes(), second.crop(box).tobytes())
                self.assertNotIn(email, json.dumps({k:v for k,v in result.items() if k != "png"}))

    def test_invalid_image_does_not_succeed_empty(self):
        with self.assertRaises(DetectionError):
            self.detector.detect(b"invalid PNG")

    def test_fresh_session_scroll_and_zoom_preserve_discoveries(self):
        detector = ScreenshotDetector()
        first = render(["Full name: Leona Voss", "Delivery address:",
                        "863 Willow Road", "Austin, TX 78701"], 22, (70, 65))
        findings = detector.detect(first)
        self.assertTrue(any(f["kind"] == "NAME" and "Leona" in f["value"] for f in findings))
        # A later viewport has moved and lost the original visible labels.
        followup = render(["Leona Voss", "Austin, TX 78701"], 22, (390, 210))
        image = Image.open(io.BytesIO(followup))
        image = image.resize((1375, 813), Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, "PNG")
        later = detector.detect(output.getvalue())
        self.assertTrue(any(f["kind"] == "NAME" for f in later), later)
        self.assertTrue(any(f["kind"] == "ADDRESS" for f in later), later)
        for finding in later:
            self.assertGreater(finding["x"], 450)
            self.assertLessEqual(finding["x"] + finding["width"], 1375)
            self.assertLessEqual(finding["y"] + finding["height"], 813)


if __name__ == "__main__":
    unittest.main()
