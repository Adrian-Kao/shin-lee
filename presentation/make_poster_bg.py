"""Decorative full-bleed background for the 全開 poster (4650×6450 @150dpi).

Gradient canvas, diagonal navy banner + footer, translucent rings, dot
grids and soft amber glows — the poster art layer. All text/content is
laid on top as vectors by build_poster.py.
"""
import os

from PIL import Image, ImageDraw, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

W, H = 4650, 6450
NAVY      = (30, 58, 138)
NAVY_DEEP = (18, 36, 92)
AMBER     = (245, 176, 32)


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make():
    # base: white → pale blue-gray vertical gradient
    base = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(base)
    top_c, bot_c = (255, 255, 255), (241, 245, 251)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=lerp(top_c, bot_c, y / H))

    # ---- banner: navy block with diagonal bottom edge ----
    d.polygon([(0, 0), (W, 0), (W, 930), (0, 1080)], fill=NAVY)
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(ov)
    # deeper navy wedge on the left for depth
    od.polygon([(0, 0), (1850, 0), (1250, 1080), (0, 1080)],
               fill=(*NAVY_DEEP, 150))
    # translucent rings on the right
    od.ellipse([4120 - 430, 330 - 430, 4120 + 430, 330 + 430],
               outline=(255, 255, 255, 30), width=34)
    od.ellipse([3590 - 230, 800 - 230, 3590 + 230, 800 + 230],
               outline=(255, 255, 255, 24), width=26)
    od.ellipse([4495 - 85, 815 - 85, 4495 + 85, 815 + 85],
               fill=(*AMBER, 220))
    # dot grid in banner, bottom-left
    for gx in range(14):
        for gy in range(5):
            x, y = 260 + gx * 82, 640 + gy * 82
            od.ellipse([x - 6, y - 6, x + 6, y + 6], fill=(255, 255, 255, 55))
    base = Image.alpha_composite(base.convert("RGBA"), ov)

    # amber top strip
    d = ImageDraw.Draw(base)
    d.rectangle([0, 0, W, 52], fill=AMBER)

    # ---- soft glows (blurred layer) ----
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([4330 - 270, 1120 - 270, 4330 + 270, 1120 + 270],
               fill=(*AMBER, 70))                  # under banner, right
    gd.ellipse([140 - 320, 4430 - 320, 140 + 320, 4430 + 320],
               fill=(*AMBER, 36))                  # left edge, section 04
    glow = glow.filter(ImageFilter.GaussianBlur(80))
    base = Image.alpha_composite(base, glow)

    # mid-page faint navy ring + side dots
    ov2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    o2 = ImageDraw.Draw(ov2)
    o2.ellipse([4480 - 400, 2950 - 400, 4480 + 400, 2950 + 400],
               outline=(*NAVY, 16), width=54)
    for gx in range(4):
        for gy in range(9):
            x, y = 4395 + gx * 70, 4950 + gy * 70
            o2.ellipse([x - 5, y - 5, x + 5, y + 5], fill=(*NAVY, 26))
    base = Image.alpha_composite(base, ov2)

    # ---- footer: navy band with diagonal top edge ----
    d = ImageDraw.Draw(base)
    d.polygon([(0, 6255), (W, 6175), (W, 6450), (0, 6450)], fill=NAVY)
    d.line([(0, 6243), (W, 6163)], fill=AMBER, width=16)

    base.convert("RGB").save(os.path.join(ASSETS, "poster_bg.png"), quality=95)
    print("poster_bg.png written", base.size)


if __name__ == "__main__":
    make()
