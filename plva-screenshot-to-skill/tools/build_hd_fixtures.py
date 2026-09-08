"""Render new 2400x1440 synthetic UI fixtures; preserve the original recording."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
import shutil

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SCALE = 3
SIZE = (800 * SCALE, 480 * SCALE)
INK, MUTED, LINE = "#18384e", "#566c7d", "#d7e2eb"


@lru_cache(maxsize=32)
def font(size, bold=False):
    names = (["C:/Windows/Fonts/segoeuib.ttf", "DejaVuSans-Bold.ttf"] if bold
             else ["C:/Windows/Fonts/segoeui.ttf", "DejaVuSans.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size * SCALE)
        except OSError:
            continue
    return ImageFont.load_default(size=size * SCALE)


def draw_screen(state, changed=False):
    image = Image.new("RGB", SIZE, "#f3f5f9")
    canvas = ImageDraw.Draw(image)

    def rect(box, fill, outline=None, radius=0):
        points = tuple(int(n * SCALE) for n in box)
        if radius:
            canvas.rounded_rectangle(points, radius=radius * SCALE, fill=fill,
                                     outline=outline, width=SCALE)
        else:
            canvas.rectangle(points, fill=fill, outline=outline, width=SCALE)

    def text(x, y, value, size=18, bold=False, color=INK):
        canvas.text((x * SCALE, y * SCALE), value, font=font(size, bold), fill=color, anchor="lt")

    def line(points, color=LINE, width=1):
        canvas.line([(int(x * SCALE), int(y * SCALE)) for x, y in points], fill=color, width=width * SCALE)

    def pill(x, y, w, value, bg="#e8efff", color="#2a56be"):
        rect((x, y, x + w, y + 26), bg, radius=13)
        text(x + 11, y + 6, value, 12, True, color)

    def lock(x, y):
        rect((x + 3, y, x + 11, y + 9), None, "#167765", 4)
        rect((x, y + 6, x + 14, y + 17), "#167765", radius=3)
        rect((x + 6, y + 10, x + 8, y + 14), "white", radius=1)

    def field(x, y, w, label, value, protected=False, dropdown=False, empty=False, invalid=False):
        text(x, y, label, 15, True)
        edge = "#d78163" if invalid else "#cbd7e2"
        rect((x, y + 25, x + w, y + 68), "#edf8f3" if protected else "white", edge, 6)
        padding = 36 if protected else 13
        if protected:
            lock(x + 12, y + 38)
        text(x + padding, y + 37, value, 17, color="#126652" if protected else MUTED if empty else INK)
        if dropdown:
            line([(x + w - 23, y + 44), (x + w - 18, y + 49), (x + w - 13, y + 44)], MUTED, 2)

    support = state == 1 and not changed
    # Functional app chrome, rather than presentation-only labels on a blank canvas.
    rect((0, 0, 800, 49), "white")
    line([(0, 49), (800, 49)])
    rect((16, 12, 41, 37), "#2255c4", radius=6)
    text(22, 16, "P", 18, True, "white")
    text(52, 16, "PLVA", 19, True)
    text(116, 18, "/", 16, color="#93a5b5")
    text(135, 18, "Support" if support else "Shipping", 16, color=MUTED)
    pill(601, 12, 176, "SYNTHETIC DEMO", "#edf2f8", "#52687c")
    rect((0, 49, 119, 480), "#11283c")
    text(16, 72, "WORKSPACE", 10, True, "#9eb3c8")
    for index, name in enumerate(["Support", "Shipping", "Activity"]):
        top = 105 + index * 46
        active = (index == 0 and support) or (index == 1 and not support)
        if active:
            rect((9, top - 9, 110, top + 28), "#274865", radius=6)
        text(19, top, name, 15, active, "white" if active else "#b7c9da")
    line([(15, 392), (103, 392)], "#345069")
    rect((17, 411, 43, 437), "#3b5670", radius=13)
    text(23, 419, "D", 13, True, "white")
    text(52, 414, "Demo", 13, True, "white")
    text(17, 450, "Local workspace", 11, color="#a6bed1")

    if support:
        text(141, 66, "Support  /  Tickets  /  DEMO-104", 12, color=MUTED)
        text(139, 90, "Replacement request", 25, True)
        pill(711, 89, 66, "Open", "#e4f3e9", "#23754f")
        rect((139, 137, 517, 447), "white", LINE, 9)
        text(155, 154, "Conversation", 16, True)
        text(403, 156, "1 message", 12, color=MUTED)
        line([(139, 186), (517, 186)])
        rect((156, 205, 188, 237), "#dce8ff", radius=16)
        text(166, 214, "C", 15, True, "#285ac5")
        text(201, 205, "Customer", 15, True)
        text(201, 226, "Replacement request", 12, color=MUTED)
        rect((155, 261, 498, 328), "#f3f6fb", radius=8)
        text(169, 277, "Please arrange a replacement", 17)
        text(169, 301, "for order DEMO-104.", 17)
        rect((155, 346, 498, 427), "#fff8e7", "#eadfbf", 7)
        text(169, 359, "INTERNAL NOTE", 11, True, "#8b6726")
        text(169, 381, "Prepare a draft using the shipping", 14)
        text(169, 402, "address attached to this ticket.", 14)
        rect((533, 137, 779, 313), "white", LINE, 9)
        text(549, 154, "Order details", 16, True)
        line([(533, 186), (779, 186)])
        text(549, 204, "Order reference", 12, color=MUTED)
        text(549, 225, "DEMO-104", 19, True)
        text(549, 259, "Requested item", 12, color=MUTED)
        text(549, 280, "USB-C hub", 17)
        rect((533, 329, 779, 447), "white", LINE, 9)
        text(549, 346, "Shipping address", 15, True)
        lock(549, 378)
        text(571, 379, "ADDRESS_1_a3f9", 16, color="#126652")
        text(549, 414, "Protected by PLVA", 12, color=MUTED)
        return image

    text(141, 66, "Shipping  /  Replacements", 12, color=MUTED)
    text(139, 90, "Replacement shipment", 25, True)
    pill(648 if state == 7 and not changed else 711, 89,
         131 if state == 7 and not changed else 66,
         "Ready for review" if state == 7 and not changed else "Draft",
         "#e4f3e9" if state == 7 and not changed else "#e7edf4",
         "#23754f" if state == 7 and not changed else "#53677c")
    rect((139, 137, 779, 400), "white", LINE, 9)
    text(156, 153, "Shipment details", 16, True)
    text(650, 157, "* Required fields", 11, color=MUTED)
    if changed:
        field(157, 190, 604, "Customer shipping address *", "ADDRESS_7_b812", True)
        field(157, 279, 282, "Replacement item *", "Wireless mouse", dropdown=True)
        field(460, 279, 301, "Order reference *", "DEMO-205")
    else:
        field(157, 190, 282, "Order reference *", "DEMO-104" if state >= 3 else "Enter order reference", empty=state < 3)
        field(460, 190, 301, "Replacement item *", "USB-C hub" if state >= 5 else "Select an item", dropdown=True, empty=state < 5, invalid=state == 4)
        field(157, 279, 604, "Customer shipping address *", "ADDRESS_1_a3f9" if state >= 6 else "Select the address from the support ticket", protected=state >= 6, empty=state < 6)

    if changed:
        rect((156, 363, 762, 388), "#fff5df", radius=4)
        text(167, 370, "Next-run input only. This workspace has not been operated.", 12, color="#875913")
    elif state == 4:
        rect((156, 363, 762, 389), "#fff0e9", radius=4)
        text(167, 370, "!  Select a replacement item before preparing the draft.", 13, color="#a45029")
    elif state == 7:
        rect((156, 363, 762, 389), "#eaf6ef", radius=4)
        text(167, 370, "Order, item, and shipping destination checked. Draft is ready.", 12, color="#1e7350")
    else:
        text(157, 373, "Protected values stay inside the PLVA workflow.", 12, color=MUTED)

    text(141, 435, "No label purchased", 12, color=MUTED)
    rect((483, 418, 578, 460), "white", "#cbd7e2", 6)
    text(506, 431, "Cancel", 15, color=MUTED)
    rect((590, 418, 779, 460), "#2459d0", radius=6)
    button = "Save for review" if changed else "View draft" if state == 7 else "Prepare draft"
    text(615 if changed else 639 if state == 7 else 628, 430, button, 16, True, "white")
    return image


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, indent=2) + "\n").encode("utf-8"))


def build():
    source = ROOT / "fixtures/shipment-demo"
    target = ROOT / "fixtures/hd/shipment-demo"
    target.mkdir(parents=True, exist_ok=True)
    (target / "frames").mkdir(exist_ok=True)
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    manifest["recording_id"] = "recording-demo-hd-003"
    for i, frame in enumerate(manifest["frames"], 1):
        path = target / frame["path"]
        draw_screen(i).save(path, optimize=True)
        frame["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    events = [json.loads(line) for line in (source / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    by_id = {event["event_id"]: event for event in events}
    by_id["e1"]["text"] = "Replacement requested for order DEMO-104, item USB-C hub. Customer shipping address is protected."
    by_id["e1"]["public_values"].append({"value": "USB-C hub", "role_hint": "replacement_item"})
    by_id["e10"]["operation"]["text"] = "USB-C hub"
    by_id["e11"]["text"] = "Replacement item USB-C hub is selected."
    by_id["e18"]["criterion"] = "Draft contains the selected order DEMO-104, replacement item USB-C hub, and matching shipping destination; no purchase was made."
    (target / "events.jsonl").write_bytes("".join(json.dumps(event) + "\n" for event in events).encode("utf-8"))
    save(target / "manifest.json", manifest)

    changed = ROOT / "fixtures/hd/changed-layout"
    changed.mkdir(parents=True, exist_ok=True)
    draw_screen(6, changed=True).save(changed / "screen.png", optimize=True)
    for name in ["new-run-bindings.json", "capabilities.json"]:
        shutil.copyfile(ROOT / "fixtures" / name, ROOT / "fixtures/hd" / name)
    bindings_path = ROOT / "fixtures/hd/new-run-bindings.json"
    bindings = json.loads(bindings_path.read_text())
    bindings["replacement_item"] = "Wireless mouse"
    save(bindings_path, bindings)
    scenario = json.loads((ROOT / "fixtures/changed-layout/scenario.json").read_text())
    scenario["layout_changes"].append("The requested product changes from USB-C hub to Wireless mouse.")
    save(changed / "scenario.json", scenario)

    files = ["manifest.json", "events.jsonl"] + [f["path"] for f in manifest["frames"]]
    parts = {p: hashlib.sha256((target / p).read_bytes()).hexdigest() for p in files}
    bundle_digest = hashlib.sha256(json.dumps(parts, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    registry_path = ROOT / "src/plva_skill_learning/data/trusted-synthetic.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    # Preserve the original pinned fixture; replace only this renderer's previous HD digest.
    metadata_path = ROOT / "fixtures/hd/render-info.json"
    previous = json.loads(metadata_path.read_text()).get("bundle_digest") if metadata_path.exists() else None
    registry["approvals"] = [a for a in registry["approvals"] if a["bundle_digest"] not in {previous, bundle_digest}]
    registry["approvals"].append({"bundle_digest": bundle_digest, "producer": "plva-synthetic-fixture", "data_class": "synthetic", "allow_cloud": False, "role_hints_trusted": True})
    save(registry_path, registry)
    save(ROOT / "fixtures/trusted-synthetic.json", registry)
    save(metadata_path, {"kind": "synthetic_render", "resolution": list(SIZE), "recording_id": manifest["recording_id"], "bundle_digest": bundle_digest, "original_recording_preserved": True})


if __name__ == "__main__":
    build()
