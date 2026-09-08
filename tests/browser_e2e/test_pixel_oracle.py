"""Small deterministic oracle tests; no browser or OCR initialization."""
import io
import unittest

from PIL import Image

from tests.browser_e2e.pixel_oracle import (
    assert_entered_pixels_masked, assert_same_visible_field, assert_moved_field_pixels_masked,
    field_pixel_box, native_visibility_diagnostics,
)


def png(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


class PixelOracleTests(unittest.TestCase):
    def setUp(self):
        self.empty = Image.new("RGB", (40, 40), "white")
        self.entered = self.empty.copy()
        self.entered.putpixel((4, 4), (0, 0, 0))
        self.protected = self.empty.copy()
        self.protected.putpixel((4, 4), (24, 36, 53))
        self.box = dict(x=2, y=2, width=10, height=10)
        self.masks = [dict(kind="EMAIL", x=4, y=4, width=1, height=1)]

    def check(self, **overrides):
        args = dict(empty_png=png(self.empty), entered_png=png(self.entered),
                    protected_png=png(self.protected), masks=self.masks,
                    field_box=self.box, viewport_size=(20, 20), kind="EMAIL",
                    minimum_pixels=1)
        args.update(overrides)
        return assert_entered_pixels_masked(**args)

    def test_scaled_border_pixel_is_checked_without_inset(self):
        self.assertEqual(self.check()["changed_pixels_masked"], 1)
        with self.assertRaisesRegex(AssertionError, "uncovered"):
            self.check(masks=[])

    def test_declared_mask_cannot_hide_retained_actual_pixel(self):
        with self.assertRaisesRegex(AssertionError, "unchanged"):
            self.check(protected_png=png(self.entered))

    def test_unstable_empty_frame_is_rejected_not_subtracted(self):
        with self.assertRaisesRegex(AssertionError, "unstable"):
            self.check(stable_empty_png=png(self.entered))

    def test_no_visible_difference_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Insufficient"):
            self.check(entered_png=png(self.empty))

    def test_wrong_class_mask_is_not_coverage(self):
        with self.assertRaisesRegex(AssertionError, "uncovered"):
            self.check(masks=[dict(self.masks[0], kind="NAME")])

    def test_outward_scaling_and_offscreen_rejection(self):
        self.assertEqual(field_pixel_box(dict(x=.2, y=.2, width=1, height=1),
                                         (40, 40), (20, 20)), (0, 0, 3, 3))
        with self.assertRaisesRegex(AssertionError, "outside"):
            field_pixel_box(dict(x=-1, y=0, width=2, height=2), (40, 40), (20, 20))

    def test_followup_ignores_outside_pixels_but_not_field_changes(self):
        alternate = self.protected.copy()
        alternate.putpixel((39, 39), (0, 0, 0))
        assert_same_visible_field(png(self.protected), png(alternate), self.box, (20, 20))
        alternate.putpixel((4, 4), (0, 0, 0))
        with self.assertRaisesRegex(AssertionError, "differ"):
            assert_same_visible_field(png(self.protected), png(alternate), self.box, (20, 20))

    def test_visibility_requires_full_text_fit_and_zero_scroll(self):
        metrics = dict(content_width=100, content_height=30, text_width=90,
                       text_height=20, scroll_left=0, scroll_top=0)
        self.assertTrue(native_visibility_diagnostics(metrics)["complete_text_fits"])
        for changed in ({"text_width": 101}, {"text_height": 31},
                        {"scroll_left": 2}, {"scroll_top": 1}):
            self.assertFalse(native_visibility_diagnostics(dict(metrics, **changed))
                             ["complete_text_fits"])
        self.assertFalse(native_visibility_diagnostics({})["complete_text_fits"])

    def moved_check(self, *, missing_mask=False, modified=False, resized=False):
        actual = self.empty.copy()
        actual.paste(self.entered.crop((4, 4, 24, 24)), (8, 10))
        safe = actual.copy()
        safe.putpixel((8, 10), (24, 36, 53))
        if modified:
            actual.putpixel((9, 11), (0, 0, 0))
        return assert_moved_field_pixels_masked(
            png(self.empty), png(self.entered), png(actual), png(safe),
            [] if missing_mask else [dict(kind='EMAIL', x=8, y=10, width=1, height=1)],
            self.box, dict(x=4, y=5, width=9 if resized else 10, height=10),
            (20, 20), 'EMAIL', stable_empty_png=png(self.empty), minimum_pixels=1)

    def test_moved_field_maps_all_glyph_pixels_to_new_location(self):
        result = self.moved_check()
        self.assertEqual(result['changed_pixels_masked'], 1)
        self.assertEqual(result['field_pixel_box'], [8, 10, 28, 30])
        with self.assertRaisesRegex(AssertionError, 'uncovered'):
            self.moved_check(missing_mask=True)

    def test_moved_field_rejects_any_changed_actual_crop(self):
        with self.assertRaisesRegex(AssertionError, 'differs'):
            self.moved_check(modified=True)

    def test_moved_field_rejects_resize(self):
        with self.assertRaisesRegex(AssertionError, 'dimensions'):
            self.moved_check(resized=True)


if __name__ == "__main__":
    unittest.main()
