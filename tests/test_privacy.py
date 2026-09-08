import io
import json
import unittest

from PIL import Image

from plva.privacy import PrivacyError, PrivacySession
from plva.detection.classify import classify_regions


def frame(color="white"):
    output = io.BytesIO()
    Image.new("RGB", (200, 80), color).save(output, format="PNG")
    return output.getvalue()


def field(value="alice@example.com", kind="EMAIL", **kwargs):
    return {"kind": kind, "value": value, "label": value,
            "x": 10.2, "y": 10.2, "width": 150, "height": 40, **kwargs}


class PrivacyTests(unittest.TestCase):
    def test_mask_replaces_pixels_and_preserves_dimensions(self):
        session = PrivacySession()
        result = session.protect(frame(), [field()])
        image = Image.open(io.BytesIO(result["png"]))
        self.assertEqual(image.size, (200, 80))
        self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        self.assertNotEqual(image.getpixel((10, 10)), (255, 255, 255))
        # Protected pixels depend only on token, never original underlying content.
        other = session.protect(frame("red"), [field()])
        second = Image.open(io.BytesIO(other["png"]))
        self.assertEqual(image.crop((10, 10, 161, 51)).tobytes(),
                         second.crop((10, 10, 161, 51)).tobytes())

    def test_tokens_stable_on_later_screens_and_resolve_locally(self):
        session = PrivacySession()
        first = session.protect(frame(), [field()])
        second = session.protect(frame(), [field(x=20)])
        self.assertEqual(first["manifest"], second["manifest"])
        self.assertEqual(session.resolve("Send to [EMAIL_1]"), "Send to alice@example.com")

    def test_metadata_does_not_echo_values_or_labels(self):
        result = PrivacySession().protect(frame(), [field()])
        del result["png"]
        self.assertNotIn("alice@example.com", json.dumps(result))

    def test_unknown_and_blocked_tokens_fail(self):
        session = PrivacySession()
        session.protect(frame(), [field("sk-demo-super-secret", "SECRET")])
        for token in ("[SECRET_1]", "[EMAIL_99]"):
            with self.assertRaises(PrivacyError):
                session.resolve(token)
        self.assertEqual(session.scrub("sk-demo-super-secret"), "[SECRET_1]")

    def test_history_scrubbing_prefers_longer_values(self):
        session = PrivacySession()
        session.protect(frame(), [field("Alice", "NAME"), field("Alice Smith", "NAME")])
        self.assertEqual(session.scrub("Alice Smith and Alice"), "[NAME_2] and [NAME_1]")
        self.assertEqual(session.scrub("unknown@example.com sk-1234567890"),
                         "[EMAIL_REDACTED] [SECRET_REDACTED]")

    def test_protection_fails_without_raw_fallback(self):
        for png, findings in ((b"not an image", []), (frame(), [field(width=0)]),
                              (frame(), [field(x=float("nan"))]),
                              (frame(), [field(kind="UNKNOWN")])):
            with self.assertRaises(PrivacyError):
                PrivacySession().protect(png, findings)

    def test_empty_observation_still_returns_fresh_png(self):
        result = PrivacySession().protect(frame(), [])
        self.assertEqual(result["count"], 0)
        self.assertEqual(result["manifest"], [])
        self.assertEqual(Image.open(io.BytesIO(result["png"])).size, (200, 80))

    def test_scrubs_new_structured_and_labelled_values(self):
        session = PrivacySession()
        self.assertEqual(session.scrub("Call +1 (628) 555-0184"), "Call [PHONE_REDACTED]")
        self.assertEqual(session.scrub("Password: fresh-cactus-42"), "Password: [SECRET_REDACTED]")
        self.assertEqual(session.scrub("Name: Rosa Vellin"), "Name: [NAME_REDACTED]")

    def test_local_known_values_are_copies_and_include_blocked_secrets(self):
        session = PrivacySession()
        session.protect(frame(), [field("unstructured-password", "SECRET")])
        copy = session.local_known_values()
        self.assertEqual(copy, [{"kind": "SECRET", "value": "unstructured-password"}])
        copy[0]["value"] = "modified"
        self.assertEqual(session.scrub("unstructured-password"), "[SECRET_1]")


class ClassificationTests(unittest.TestCase):
    @staticmethod
    def rows(*texts):
        return [dict(text=text, x=17, y=10+i*25, width=170, height=18,
                     confidence=.91) for i, text in enumerate(texts)]

    def test_fresh_contact_and_credentials(self):
        findings = classify_regions(self.rows("Full name: Rosa Vellin", "rv.27@sample.net",
                                              "+1 (628) 555-0184", "Password: fresh-cactus-42"))
        values = {(f["kind"], f["value"]) for f in findings}
        self.assertIn(("NAME", "Rosa Vellin"), values)
        self.assertIn(("EMAIL", "rv.27@sample.net"), values)
        self.assertIn(("PHONE", "+1 (628) 555-0184"), values)
        self.assertIn(("SECRET", "fresh-cactus-42"), values)

    def test_multiline_address_without_expected_values(self):
        findings = classify_regions(self.rows("Shipping address", "Rosa Vellin",
                                              "819 Walnut Road", "Albany, NY 12207", "Continue"))
        address = next(f for f in findings if f["source"] == "visible-label")
        self.assertEqual(address["value"], "Rosa Vellin\n819 Walnut Road\nAlbany, NY 12207")
        self.assertEqual((address["y"], address["height"]), (35, 68))
        self.assertNotIn("Continue", address["value"])

    def test_side_by_side_label_and_value(self):
        rows = [dict(text="Name", x=10, y=10, width=60, height=20),
                dict(text="Cora Feld", x=130, y=10, width=130, height=20)]
        finding = classify_regions(rows)[0]
        self.assertEqual(finding["value"], "Cora Feld")
        self.assertEqual(finding["x"], 130)

    def test_plain_name_requires_context_but_vault_finds_later_occurrence(self):
        rows = self.rows("Cora Feld")
        self.assertEqual(classify_regions(rows), [])
        finding = classify_regions(rows, [{"kind": "NAME", "value": "Cora Feld"}])[0]
        self.assertEqual(finding["source"], "local-vault")
        self.assertEqual(classify_regions(self.rows("Nameplate", "Addressable LEDs")), [])

    def test_full_region_mask_covers_surrounding_ocr_pixels(self):
        rows = self.rows("Email: rv.27@sample.net")
        findings = classify_regions(rows)
        first = PrivacySession().protect(frame("white"), findings)
        second = PrivacySession().protect(frame("red"), findings)
        one = Image.open(io.BytesIO(first["png"]))
        two = Image.open(io.BytesIO(second["png"]))
        self.assertEqual(one.crop((17, 10, 187, 28)).tobytes(),
                         two.crop((17, 10, 187, 28)).tobytes())


if __name__ == "__main__":
    unittest.main()
