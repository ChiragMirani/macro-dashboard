"""Generate a 1280x640 social-preview card matching the icon design."""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parents[1] / "docs" / "social-preview.png"

BG = (10, 22, 40)
FG = (255, 255, 255)
MUTED = (170, 180, 200)
ACCENT = (10, 195, 130)


def find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def main() -> None:
    W, H = 1280, 640
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # Big chart line across the bottom-third
    pts = [
        (80,  H - 120),
        (350, H - 200),
        (560, H - 160),
        (820, H - 280),
        (1080, H - 220),
        (1200, H - 320),
    ]
    draw.line(pts, fill=ACCENT, width=8, joint="curve")
    cx, cy = pts[-1]
    r = 14
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=ACCENT)

    title = "MacroForecastbyCM"
    sub   = "Live US macro release schedule"
    sub2  = "House forecasts vs Kalshi consensus, settled against actuals."
    by    = "by Chirag Mirani"

    f_title = find_font(96, bold=True)
    f_sub   = find_font(38)
    f_sub2  = find_font(28)
    f_by    = find_font(28, bold=True)

    draw.text((80, 110), title, fill=FG,    font=f_title)
    draw.text((80, 230), sub,   fill=FG,    font=f_sub)
    draw.text((80, 285), sub2,  fill=MUTED, font=f_sub2)
    draw.text((80, 360), by,    fill=ACCENT,font=f_by)

    img.save(OUT, optimize=True)
    print(f"Wrote {OUT}  ({W}x{H})")


if __name__ == "__main__":
    main()
