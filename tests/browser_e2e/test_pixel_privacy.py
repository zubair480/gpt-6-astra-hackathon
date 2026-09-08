"""Independent pixel assertions; these unit tests are not live-provider evidence.

The detector acceptance test passes PNG bytes only and skips only when the
detector module is absent. Runtime/model failures remain failures.
"""
import importlib.util
import io
import json
import secrets
import unittest

from PIL import Image, ImageDraw, ImageFont

from plva.privacy import PrivacyError, PrivacySession


def synthetic_frame():
    """Generate fresh values locally, without registering them with a detector."""
    nonce = secrets.token_hex(5)
    values = {
        "EMAIL": f"case.{nonce}@example.net",
        "NAME": secrets.choice(("Mira", "Elena", "Naomi", "Tessa")) + " "
                + secrets.choice(("Ellison", "Whitaker", "Mercer", "Bennett")),
        "ADDRESS": f"{secrets.randbelow(8000) + 1000} Cedar Lane, Boston, MA 02110",
        "PHONE": f"+1 (202) 555-{secrets.randbelow(10000):04d}",
        "SECRET": f"sk-{secrets.token_hex(14)}",
    }
    frame = Image.new("RGB", (1200, 500), "white")
    draw = ImageDraw.Draw(frame)
    font = ImageFont.load_default(size=25)
    findings = []
    for index, (kind, value) in enumerate(values.items()):
        y = 35 + index * 85
        draw.text((20, y), kind.title() + ":", fill="black", font=font)
        bounds = draw.textbbox((185, y), value, font=font)
        draw.text((185, y), value, fill="black", font=font)
        findings.append(dict(kind=kind, value=value, label=value,
                             x=bounds[0] - 2, y=bounds[1] - 2,
                             width=bounds[2] - bounds[0] + 4,
                             height=bounds[3] - bounds[1] + 4))
    output = io.BytesIO()
    frame.save(output, "PNG")
    return output.getvalue(), findings


def decoded(png):
    with Image.open(io.BytesIO(png)) as image:
        return image.convert("RGB")


class IndependentPixelPrivacyTests(unittest.TestCase):
    def test_every_mask_pixel_independent_of_underlying_private_pixels(self):
        png, findings = synthetic_frame()
        privacy = PrivacySession()
        protected = privacy.protect(png, findings)
        altered = decoded(png)
        draw = ImageDraw.Draw(altered)
        for finding in findings:
            x, y = finding["x"], finding["y"]
            draw.rectangle((x, y, x + finding["width"] - 1,
                            y + finding["height"] - 1), fill="#fa107f")
        output = io.BytesIO()
        altered.save(output, "PNG")
        alternate = privacy.protect(output.getvalue(), findings)
        self.assertEqual(decoded(protected["png"]).tobytes(),
                         decoded(alternate["png"]).tobytes())
        original, safe = decoded(png), decoded(protected["png"])
        self.assertEqual(original.size, safe.size)
        self.assertNotEqual(original.tobytes(), safe.tobytes())
        for finding in findings:
            x, y = finding["x"], finding["y"]
            box = (x, y, x + finding["width"], y + finding["height"])
            # Black source glyphs cannot survive in dark-blue/teal masks.
            self.assertIn((0, 0, 0), original.crop(box).get_flattened_data())
            self.assertNotIn((0, 0, 0), safe.crop(box).get_flattened_data())
        self.assertEqual(original.crop((0, 0, 175, 500)).tobytes(),
                         safe.crop((0, 0, 175, 500)).tobytes())

    def test_manifest_labels_and_scrubbed_text_have_no_generated_values(self):
        png, findings = synthetic_frame()
        privacy = PrivacySession()
        protected = privacy.protect(png, findings)
        metadata = json.dumps({key: value for key, value in protected.items()
                               if key != "png"})
        text = privacy.scrub(" | ".join(row["value"] for row in findings))
        for finding in findings:
            self.assertNotIn(finding["value"], metadata)
            self.assertNotIn(finding["value"], text)
        self.assertEqual(len(protected["manifest"]), 5)
        self.assertIn("[SECRET_1]", text)
        with self.assertRaises(PrivacyError):
            privacy.resolve("[SECRET_1]")

    def test_followup_frame_preserves_tokens_and_masks_moved_values(self):
        png, findings = synthetic_frame()
        privacy = PrivacySession()
        first = privacy.protect(png, findings)
        shifted = Image.new("RGB", (1220, 520), "white")
        shifted.paste(decoded(png), (13, 17))
        output = io.BytesIO()
        shifted.save(output, "PNG")
        moved = [dict(row, x=row["x"] + 13, y=row["y"] + 17)
                 for row in findings]
        second = privacy.protect(output.getvalue(), moved)
        self.assertEqual(first["manifest"], second["manifest"])
        for before, after in zip(first["masks"], second["masks"]):
            def crop(result, mask):
                x, y = mask["x"], mask["y"]
                return decoded(result["png"]).crop(
                    (x, y, x + mask["width"], y + mask["height"])).tobytes()
            self.assertEqual(crop(first, before), crop(second, after))


class PngOnlyDetectorAcceptance(unittest.TestCase):
    def assert_detected_and_masked(self, kind, *, small=False, multiline=False):
        if importlib.util.find_spec("plva.detection") is None:
            self.skipTest("plva.detection missing; PNG-only detection is UNPROVEN")
        from plva.detection import ScreenshotDetector
        detector = ScreenshotDetector()
        _, truth = synthetic_frame()  # Generated AFTER detector initialization.
        expected = next(row for row in truth if row["kind"] == kind)
        value = expected["value"]
        if multiline:
            value = value.replace(", Boston", "\nBoston")
        frame = Image.new("RGB", (1200, 230), "white")
        draw = ImageDraw.Draw(frame)
        font = ImageFont.load_default(size=16 if small else 25)
        # A visible human-readable label is permitted; there are no annotations,
        # DOM elements, metadata hints, or truth values passed to the detector.
        draw.text((20, 20), kind.title() + ":", fill="black", font=font)
        box = draw.multiline_textbbox((20, 65), value, font=font, spacing=9)
        draw.multiline_text((20, 65), value, fill="black", font=font, spacing=9)
        output = io.BytesIO()
        frame.save(output, "PNG")
        png = output.getvalue()
        findings = detector.detect(png)  # Sole input: encoded pixels, no DOM/hints.
        normalize = lambda text: " ".join(text.split())
        matches = [row for row in findings if row["kind"] == kind
                   and normalize(row["value"]) == normalize(value)]
        self.assertTrue(matches, f"PNG detector missed generated {kind}; "
                        f"small={small}, multiline={multiline}")
        protected = PrivacySession().protect(png, findings)
        source, safe = decoded(png), decoded(protected["png"])
        coverage = Image.new("1", source.size, 0)
        draw = ImageDraw.Draw(coverage)
        for mask in protected["masks"]:
            if mask["kind"] != kind:
                continue
            x, y = mask["x"], mask["y"]
            draw.rectangle((x, y, x + mask["width"] - 1,
                            y + mask["height"] - 1), fill=1)
        glyph_count = 0
        for y in range(box[1], box[3]):
            for x in range(box[0], box[2]):
                if source.getpixel((x, y)) != (255, 255, 255):
                    glyph_count += 1
                    self.assertTrue(coverage.getpixel((x, y)),
                                    f"Unmasked {kind} glyph at {(x, y)}")
                    self.assertNotEqual(source.getpixel((x, y)), safe.getpixel((x, y)))
        self.assertGreater(glyph_count, 100)

    def test_email_png_only(self):
        self.assert_detected_and_masked("EMAIL")

    def test_name_png_only(self):
        self.assert_detected_and_masked("NAME")

    def test_address_png_only(self):
        self.assert_detected_and_masked("ADDRESS")

    def test_phone_png_only(self):
        self.assert_detected_and_masked("PHONE")

    def test_secret_png_only(self):
        self.assert_detected_and_masked("SECRET")

    def test_small_email_png_only(self):
        self.assert_detected_and_masked("EMAIL", small=True)

    def test_multiline_address_png_only(self):
        self.assert_detected_and_masked("ADDRESS", multiline=True)


if __name__ == "__main__":
    unittest.main()
