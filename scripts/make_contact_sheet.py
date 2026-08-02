#!/usr/bin/env python3
"""Builds docs/contact_sheet.png from the rendered thumbnails in assets/.thumbs.

Run with the host's python3 (needs Pillow) after scripts/build_library.py,
since Blender's bundled Python doesn't have Pillow available.
"""
import os
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
THUMBS_DIR = os.path.join(ROOT, "assets", ".thumbs")
OUT_PATH = os.path.join(ROOT, "docs", "contact_sheet.png")

ORDER = [
    "Cube", "Sphere", "Ico_Sphere", "Cylinder", "Cone", "Torus", "Plane",
    "Rounded_Cube", "Tube", "Dome", "Wedge", "Stairs", "Pyramid", "Hex_Prism",
]

COLS = 7
CELL = 256
PAD = 12
BG = (30, 30, 30, 255)

names = [n for n in ORDER if os.path.exists(os.path.join(THUMBS_DIR, n + ".png"))]
rows = (len(names) + COLS - 1) // COLS

sheet_w = COLS * CELL + (COLS + 1) * PAD
sheet_h = rows * CELL + (rows + 1) * PAD
sheet = Image.new("RGBA", (sheet_w, sheet_h), BG)

for i, name in enumerate(names):
    img = Image.open(os.path.join(THUMBS_DIR, name + ".png")).convert("RGBA")
    img = img.resize((CELL, CELL), Image.LANCZOS)
    row, col = divmod(i, COLS)
    x = PAD + col * (CELL + PAD)
    y = PAD + row * (CELL + PAD)
    sheet.alpha_composite(img, (x, y))

os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
sheet.convert("RGB").save(OUT_PATH)
print(f"Wrote {OUT_PATH} ({sheet_w}x{sheet_h}, {len(names)} thumbnails)")
