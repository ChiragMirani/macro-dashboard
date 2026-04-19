"""Generate favicon + Apple touch icon + PWA icons for the dashboard."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


DOCS = Path(__file__).resolve().parents[1] / "docs"

BG = (10, 22, 40)        # deep navy
FG = (255, 255, 255)
ACCENT = (10, 195, 130)  # green up-trend line


def find_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/Arial Bold.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render(size: int) -> Image.Image:
    img = Image.new("RGB", (size, size), BG)
    draw = ImageDraw.Draw(img)

    # Stylized up-trending line chart along the bottom — bottom-left to upper-right,
    # one mid dip, ending with a dot. Sized as a fraction of the icon.
    pad = size * 0.16
    x0, x1 = pad, size - pad
    y_top, y_bot = size * 0.55, size * 0.78
    points = [
        (x0,                         y_bot),
        (x0 + (x1 - x0) * 0.30,      y_bot - (y_bot - y_top) * 0.45),
        (x0 + (x1 - x0) * 0.55,      y_bot - (y_bot - y_top) * 0.20),
        (x0 + (x1 - x0) * 0.78,      y_bot - (y_bot - y_top) * 0.75),
        (x1,                         y_top - (y_bot - y_top) * 0.25),
    ]
    line_w = max(2, int(size * 0.025))
    draw.line(points, fill=ACCENT, width=line_w, joint="curve")
    dot_r = max(3, int(size * 0.04))
    cx, cy = points[-1]
    draw.ellipse((cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r), fill=ACCENT)

    # "CM" monogram, top-centered.
    font = find_font(int(size * 0.42))
    text = "CM"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) // 2 - bbox[0]
    ty = int(size * 0.10) - bbox[1]
    draw.text((tx, ty), text, fill=FG, font=font)

    return img


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    targets = [
        ("favicon-32.png",      32),
        ("favicon-192.png",    192),
        ("favicon-512.png",    512),
        ("apple-touch-icon.png", 180),
    ]
    for name, size in targets:
        img = render(size)
        path = DOCS / name
        img.save(path, optimize=True)
        print(f"  wrote {path}  ({size}x{size})")

    # Multi-size .ico for legacy browsers / GitHub repo display
    ico_sizes = [(16, 16), (32, 32), (48, 48), (64, 64)]
    base = render(64)
    base.save(DOCS / "favicon.ico", format="ICO", sizes=ico_sizes)
    print(f"  wrote {DOCS / 'favicon.ico'}  (multi-size)")


if __name__ == "__main__":
    main()
