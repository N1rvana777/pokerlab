"""Reproduce Windows application icons with Pillow, without image services.

python pokerstudio/desktop-assets/generate_icons.py
Pass --preview-dir <directory> to also write PNG previews for inspection.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw

SIZES = [(n, n) for n in (256, 128, 64, 48, 32, 16)]
SCALE = 4


class Shapes:
    def __init__(self):
        self.image = Image.new("RGBA", (256*SCALE, 256*SCALE), (0, 0, 0, 0))
        self.draw = ImageDraw.Draw(self.image)

    def rect(self, box, fill, radius=0, outline=None, width=1):
        coords = tuple(round(v*SCALE) for v in box)
        self.draw.rounded_rectangle(coords, radius=radius*SCALE, fill=fill,
                                    outline=outline, width=width*SCALE)

    def polygon(self, points, fill):
        self.draw.polygon([(round(x*SCALE), round(y*SCALE)) for x, y in points], fill=fill)

    def ellipse(self, box, fill):
        self.draw.ellipse(tuple(round(v*SCALE) for v in box), fill=fill)

    def spade(self, cx, cy, size, color):
        r = size/2
        self.ellipse((cx-r, cy-r*.05, cx, cy+r*.95), color)
        self.ellipse((cx, cy-r*.05, cx+r, cy+r*.95), color)
        self.polygon([(cx-r,cy+r*.48),(cx+r,cy+r*.48),(cx,cy-r)], color)
        self.polygon([(cx-r*.32,cy+r*1.24),(cx+r*.32,cy+r*1.24),(cx,cy+r*.37)], color)

    def finish(self):
        return self.image.resize((256, 256), Image.Resampling.LANCZOS)


def studio_icon():
    s = Shapes()
    s.rect((6, 6, 250, 250), "#0b1823", 49)
    s.rect((25, 40, 231, 216), "#133746", 22, "#42d5c1", 10)
    # Film sprockets remain distinct when the icon is reduced to 16 pixels.
    for x in (57, 96, 135, 174):
        s.rect((x, 51, x+17, 65), "#42d5c1", 3)
        s.rect((x, 191, x+17, 205), "#42d5c1", 3)
    s.polygon([(88, 88), (88, 173), (156, 130)], "#f7fbfc")
    # Separate card cue makes the editing application identifiable as poker.
    s.rect((158, 130, 221, 219), "#f6f8ee", 11, "#0b1823", 3)
    s.spade(190, 170, 37, "#112932")
    return s.finish()


def solver_icon():
    s = Shapes()
    s.rect((6, 6, 250, 250), "#12223c", 49)
    s.rect((26, 27, 230, 229), "#203a54", 22, "#94badd", 5)
    colors = [["#42d5c1", "#2da790", "#cbb566"],
              ["#518eac", "#18324b", "#df8056"],
              ["#729cb9", "#3dbb97", "#d19f63"]]
    for row in range(3):
        for col in range(3):
            x, y = 41+col*61, 42+row*61
            s.rect((x, y, x+52, y+52), colors[row][col], 8)
    # The grid is a solver/range cue, not a chart containing invented results.
    s.spade(128, 123, 48, "#f5f8fd")
    return s.finish()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--preview-dir", type=Path)
    args = parser.parse_args()
    destination = Path(__file__).resolve().parent
    for name, image in (("pokerstudio", studio_icon()), ("pokerlab", solver_icon())):
        path = destination/(name+".ico")
        image.save(path, format="ICO", sizes=SIZES)
        # Confirm actual embedded sizes instead of trusting the save request.
        with Image.open(path) as icon:
            if icon.ico.sizes() != set(SIZES):
                raise RuntimeError("ICO size table does not match requested sizes")
        if args.preview_dir:
            args.preview_dir.mkdir(parents=True, exist_ok=True)
            image.save(args.preview_dir/(name+".png"))
        print(path)


if __name__ == "__main__":
    main()
