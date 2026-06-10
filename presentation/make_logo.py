# -*- coding: utf-8 -*-
"""PatentMind logo generator (Pillow only).

Concept: a navy shield (trust / on-prem security — the project's moat) holding
document lines that an amber "AI node" is reading. Produces:
  assets/logo_mark.png          icon only, transparent
  assets/logo_word_navy.png     mark + wordmark in navy (for light bg)
  assets/logo_word_white.png    mark + wordmark in white (for navy bg)
"""
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

NAVY      = (30, 58, 138)     # #1e3a8a
NAVY_LITE = (41, 82, 200)
NAVY_DEEP = (18, 36, 92)
AMBER     = (245, 176, 32)    # warm gold accent
WHITE     = (255, 255, 255)
INK       = (23, 32, 56)

FONT_BD = "C:/Windows/Fonts/arialbd.ttf"
FONT_RG = "C:/Windows/Fonts/arial.ttf"
FONT_CJK = "C:/Windows/Fonts/msjh.ttc"


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_mask(size, radius, ss=4):
    """High-res rounded-rect alpha mask, downsampled for smooth edges."""
    w, h = size
    m = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, w * ss, h * ss], radius=radius * ss, fill=255)
    return m.resize(size, Image.LANCZOS)


def diagonal_gradient(size, c0, c1):
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x / w + y / h) / 2
            px[x, y] = lerp(c0, c1, t)
    return img


def make_mark(px=512):
    """The icon tile."""
    ss = 3
    S = px * ss
    # navy squircle tile with diagonal gradient
    tile = diagonal_gradient((S, S), NAVY_LITE, NAVY_DEEP)
    tile = tile.convert("RGBA")
    mask = rounded_mask((S, S), radius=int(S * 0.235))
    tile.putalpha(mask)

    d = ImageDraw.Draw(tile)

    # --- shield (white, centered) ---
    cx = S / 2
    sw = S * 0.46          # shield half-width
    top = S * 0.235
    shoulder = S * 0.55
    bottom = S * 0.78
    shield = [
        (cx - sw, top),
        (cx + sw, top),
        (cx + sw, shoulder),
        (cx, bottom),
        (cx - sw, shoulder),
    ]
    # soft shadow behind shield
    sh = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sh).polygon([(x, y + S * 0.012) for x, y in shield],
                               fill=(10, 20, 50, 90))
    from PIL import ImageFilter
    sh = sh.filter(ImageFilter.GaussianBlur(S * 0.012))
    tile = Image.alpha_composite(tile, sh)
    d = ImageDraw.Draw(tile)
    d.polygon(shield, fill=WHITE)

    # --- document lines inside shield (navy) ---
    lx = cx - sw * 0.52
    rx = cx + sw * 0.52
    line_h = S * 0.026
    ys = [top + S * 0.085, top + S * 0.16, top + S * 0.235]
    widths = [0.66, 1.0, 0.82]   # last full-ish, ragged like text
    for y, wfrac in zip(ys, widths):
        x1 = lx + (rx - lx) * wfrac
        d.rounded_rectangle([lx, y, x1, y + line_h], radius=line_h / 2, fill=NAVY)

    # --- AI node + link (amber): the "mind" reading the doc ---
    node_r = S * 0.052
    nx, ny = rx + sw * 0.02, top + S * 0.085 + line_h / 2
    # connector from first line to node
    d.line([(lx + (rx - lx) * 0.66, ny), (nx, ny)], fill=AMBER, width=int(S * 0.012))
    # second small node lower
    n2x, n2y = nx + S * 0.0, ny + S * 0.11
    d.line([(nx, ny), (n2x, n2y)], fill=AMBER, width=int(S * 0.012))
    for (ox, oy, r) in [(nx, ny, node_r), (n2x, n2y, node_r * 0.72)]:
        d.ellipse([ox - r, oy - r, ox + r, oy + r], fill=AMBER)
        d.ellipse([ox - r * 0.4, oy - r * 0.4, ox + r * 0.4, oy + r * 0.4], fill=WHITE)

    # checkmark at shield base (verified / accountable)
    ckx, cky = cx, bottom - S * 0.12
    d.line([(ckx - S * 0.07, cky), (ckx - S * 0.02, cky + S * 0.06),
            (ckx + S * 0.10, cky - S * 0.075)],
           fill=NAVY, width=int(S * 0.03), joint="curve")

    out = tile.resize((px, px), Image.LANCZOS)
    out.save(os.path.join(ASSETS, "logo_mark.png"))
    return out


def make_wordmark(mark, text_color, sub_color, accent, fname, tagline=True):
    """mark + 'PatentMind AI' wordmark on transparent bg."""
    H = 320
    mark_sz = 300
    pad = 18
    name_font = ImageFont.truetype(FONT_BD, 150)
    ai_font = ImageFont.truetype(FONT_BD, 80)
    tag_font = ImageFont.truetype(FONT_CJK, 52)

    # measure
    tmp = Image.new("RGBA", (10, 10))
    td = ImageDraw.Draw(tmp)
    name = "PatentMind"
    nb = td.textbbox((0, 0), name, font=name_font)
    name_w = nb[2] - nb[0]
    ai_w = td.textbbox((0, 0), "AI", font=ai_font)[2]
    text_x = mark_sz + 56
    tag = "專利 OA 答辯自動擬稿系統 · AI Drafting Assistant"
    tag_w = td.textbbox((0, 0), tag, font=tag_font)[2]
    total_w = text_x + max(name_w + 30 + ai_w, tag_w if tagline else 0) + pad

    img = Image.new("RGBA", (total_w, H), (0, 0, 0, 0))
    img.alpha_composite(mark.resize((mark_sz, mark_sz), Image.LANCZOS),
                        (0, (H - mark_sz) // 2))
    d = ImageDraw.Draw(img)
    ty = 56 if tagline else (H - 150) // 2
    d.text((text_x, ty), name, font=name_font, fill=text_color)
    # "AI" in accent
    d.text((text_x + name_w + 30, ty + 60), "AI", font=ai_font, fill=accent)
    if tagline:
        d.text((text_x + 4, ty + 168), tag, font=tag_font, fill=sub_color)
    img.save(os.path.join(ASSETS, fname))
    return img


if __name__ == "__main__":
    mark = make_mark(512)
    make_wordmark(mark, NAVY, (90, 105, 140), (200, 130, 10),
                  "logo_word_navy.png")
    make_wordmark(mark, WHITE, (180, 195, 230), AMBER,
                  "logo_word_white.png")
    print("logo assets written to", ASSETS)
