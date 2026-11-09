"""Prepare avatar / body photos: remove the background and normalize to the project canvas.

Canvas: 600 x 1200 px (width x height), white background, figure height 1100 px,
figure top at y = 50 (so the feet end near y = 1150), centered horizontally.

Usage (put the photos in one folder, run from that folder or pass the folder):
    python prep.py [input_dir] [output_dir]
Default input_dir = current directory, output_dir = ./output
"""
import sys
from pathlib import Path

from PIL import Image
from rembg import new_session, remove

W, H, TOP, FIG_H = 600, 1200, 50, 1100
BG = (255, 255, 255)
EXT = {".png", ".jpg", ".jpeg", ".webp"}


def main() -> None:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("output")
    out.mkdir(parents=True, exist_ok=True)
    session = new_session("u2net_human_seg")  # human-tuned model; alternative: "isnet-general-use"

    for f in sorted(src.iterdir()):
        if f.suffix.lower() not in EXT or f.parent.resolve() == out.resolve():
            continue
        cut = remove(Image.open(f).convert("RGB"), session=session)  # RGBA
        bbox = cut.getbbox()
        if bbox is None:
            print("skip (nothing found):", f.name)
            continue
        cut = cut.crop(bbox)
        w = round(cut.width * FIG_H / cut.height)
        cut = cut.resize((w, FIG_H), Image.LANCZOS)
        if w > W:
            print("warning: figure wider than the canvas, check pose:", f.name, w)
        canvas = Image.new("RGB", (W, H), BG)
        canvas.paste(cut, ((W - w) // 2, TOP), cut)
        canvas.save(out / f"{f.stem}.png")
        print("done:", f.name)


if __name__ == "__main__":
    main()
