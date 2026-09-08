"""Verifier-only PNG/geometry checks. Never feed these inputs to the detector.

The field must be blurred and the page stable for both empty and entered frames.
Changed pixels are a conservative glyph superset: no arbitrary border is excluded.
Native-field visibility diagnostics complement, not replace, exact OCR and pixels.
"""
import io
import math

from PIL import Image, ImageDraw


def rgb(png):
    with Image.open(io.BytesIO(png)) as source:
        return source.convert("RGB")


def field_pixel_box(field_box, png_size, viewport_size):
    """Round outward from CSS coordinates; reject partial/offscreen fields."""
    width, height = viewport_size
    if width <= 0 or height <= 0:
        raise AssertionError("Missing positive CSS viewport dimensions")
    x, y, w, h = (float(field_box[key]) for key in ("x", "y", "width", "height"))
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise AssertionError("Invalid field geometry")
    if x < 0 or y < 0 or x + w > width or y + h > height:
        raise AssertionError("Field is partly outside captured viewport")
    sx, sy = png_size[0] / width, png_size[1] / height
    return (math.floor(x * sx), math.floor(y * sy),
            math.ceil((x + w) * sx), math.ceil((y + h) * sy))


def assert_entered_pixels_masked(empty_png, entered_png, protected_png, masks,
                                field_box, viewport_size, kind, *,
                                stable_empty_png=None, minimum_pixels=50):
    """Assert *all* independent changed field pixels are concealed, return counts.

An optional repeated empty screenshot diagnoses animations, focus/hover or layout
changes before filling. It never subtracts unstable pixels from the oracle.
"""
    empty, entered, protected = map(rgb, (empty_png, entered_png, protected_png))
    if not (empty.size == entered.size == protected.size):
        raise AssertionError("Capture dimensions changed; pixel comparison invalid")
    box = field_pixel_box(field_box, entered.size, viewport_size)
    if stable_empty_png is not None:
        stable = rgb(stable_empty_png)
        if stable.size != empty.size or stable.crop(box).tobytes() != empty.crop(box).tobytes():
            raise AssertionError("Empty field is unstable; changed pixels cannot identify glyphs")
    coverage = Image.new("1", entered.size, 0)
    draw = ImageDraw.Draw(coverage)
    for mask in masks:
        if mask["kind"] != kind:
            continue
        x, y, w, h = (mask[key] for key in ("x", "y", "width", "height"))
        draw.rectangle((x, y, x + w - 1, y + h - 1), fill=1)
    changed = uncovered = retained = 0
    first_uncovered = first_retained = None
    for y in range(box[1], box[3]):
        for x in range(box[0], box[2]):
            pixel = entered.getpixel((x, y))
            if pixel == empty.getpixel((x, y)):
                continue
            changed += 1
            if not coverage.getpixel((x, y)):
                uncovered += 1
                first_uncovered = first_uncovered or (x, y)
            if pixel == protected.getpixel((x, y)):
                retained += 1
                first_retained = first_retained or (x, y)
    if changed < minimum_pixels:
        raise AssertionError(f"Insufficient independent entered pixels: {changed}")
    if uncovered or retained:
        raise AssertionError(f"{kind}: {uncovered}/{changed} entered pixels uncovered "
                             f"(first {first_uncovered}); {retained} unchanged in protected "
                             f"PNG (first {first_retained})")
    return {"changed_pixels_masked": changed, "uncovered_pixels": uncovered,
            "retained_pixels": retained, "field_pixel_box": list(box)}


def assert_same_visible_field(first_png, second_png, field_box, viewport_size):
    """Compare decoded field pixels, independently of PNG encoding and page chrome.

Use in addition to assert_entered_pixels_masked on the executor's actual followup.
This comparison alone does not establish masking or full text visibility.
"""
    first, second = rgb(first_png), rgb(second_png)
    if first.size != second.size:
        raise AssertionError("Followup changed viewport dimensions")
    box = field_pixel_box(field_box, first.size, viewport_size)
    if first.crop(box).tobytes() != second.crop(box).tobytes():
        raise AssertionError("Followup field pixels differ from independently verified field")


def assert_moved_field_pixels_masked(empty_png, filled_png, actual_png,
                                    protected_png, masks, original_field_box,
                                    actual_field_box, viewport_size, kind, *,
                                    stable_empty_png, minimum_pixels=50):
    """Verify a moved actual field without clearing/refilling it for the oracle.

    Exact decoded filled-crop equality is mandatory, including borders/background.
    Original stable empty pixels are translated only within that identical crop;
    no actual followup pixels are excluded because of movement or instability.
    Both captures must use the supplied CSS viewport dimensions and pixel scale.
    """
    empty, filled, actual, protected, stable = map(
        rgb, (empty_png, filled_png, actual_png, protected_png, stable_empty_png))
    if not (empty.size == filled.size == actual.size == protected.size == stable.size):
        raise AssertionError("Moved field requires unchanged capture dimensions and scale")
    old_box = field_pixel_box(original_field_box, filled.size, viewport_size)
    new_box = field_pixel_box(actual_field_box, actual.size, viewport_size)
    old_size = (old_box[2] - old_box[0], old_box[3] - old_box[1])
    new_size = (new_box[2] - new_box[0], new_box[3] - new_box[1])
    if old_size != new_size:
        raise AssertionError("Moved field changed pixel dimensions")
    if empty.crop(old_box).tobytes() != stable.crop(old_box).tobytes():
        raise AssertionError("Original empty field is unstable")
    if filled.crop(old_box).tobytes() != actual.crop(new_box).tobytes():
        raise AssertionError("Actual moved field differs from original filled pixels")
    translated_empty = actual.copy()
    translated_empty.paste(empty.crop(old_box), new_box[:2])
    output = io.BytesIO()
    translated_empty.save(output, "PNG")
    result = assert_entered_pixels_masked(
        output.getvalue(), actual_png, protected_png, masks, actual_field_box,
        viewport_size, kind, minimum_pixels=minimum_pixels)
    result["original_field_pixel_box"] = list(old_box)
    return result


def native_visibility_diagnostics(metrics):
    """Return value-free clipping diagnostics from local verifier measurements.

Required measurements: content_width/height exclude CSS padding/border;
    text_width/height measure the complete value with the actual computed font,
    spacing, wrapping and line height. Input scrollWidth alone is insufficient.
    These are conservative geometry checks, not proof against external occlusion.
    """
    required = ("content_width", "content_height", "text_width", "text_height",
                "scroll_left", "scroll_top")
    try:
        measured = {key: float(metrics[key]) for key in required}
    except (KeyError, TypeError, ValueError):
        return {"complete_text_fits": False, "reason": "missing visibility measurements"}
    if not all(math.isfinite(v) for v in measured.values()):
        return {"complete_text_fits": False, "reason": "nonfinite visibility measurements"}
    fits = (measured["content_width"] > 0 and measured["content_height"] > 0
            and 0 < measured["text_width"] <= measured["content_width"]
            and 0 < measured["text_height"] <= measured["content_height"]
            and measured["scroll_left"] == 0 and measured["scroll_top"] == 0)
    return {"complete_text_fits": fits, "measurements": measured,
            "reason": "geometry fits; inspect occlusion separately" if fits
            else "text clipping or scroll displacement"}
