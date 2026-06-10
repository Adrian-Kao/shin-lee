# -*- coding: utf-8 -*-
"""Architecture diagram for PatentMind, drawn with Pillow.

Horizontal trust pipeline:  前端 SPA  ->  Gateway(digiRunner)  ->  AI Engine(Dify)  ->  Vector/LLM
Custom-drawn so it reads as designed, not a slide full of default boxes.
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

NAVY      = (30, 58, 138)
NAVY_DEEP = (18, 36, 92)
NAVY_LITE = (41, 82, 200)
AMBER     = (245, 176, 32)
WHITE     = (255, 255, 255)
INK       = (28, 38, 64)
GRAY      = (110, 124, 156)
PALE      = (240, 243, 250)
PALE_LINE = (210, 218, 235)

CJK   = "C:/Windows/Fonts/msjh.ttc"
CJK_B = "C:/Windows/Fonts/msjhbd.ttc"
LAT_B = "C:/Windows/Fonts/arialbd.ttf"


def F(path, sz):
    return ImageFont.truetype(path, sz)


def text(d, xy, s, font, fill, anchor="la"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def rrect(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def shadowed_card(base, box, r, fill, blur=14, alpha=60, dy=8):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sd.rounded_rectangle([box[0], box[1] + dy, box[2], box[3] + dy],
                         radius=r, fill=(15, 25, 55, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh)
    ImageDraw.Draw(base).rounded_rectangle(box, radius=r, fill=fill)


def make():
    W, H = 2360, 1180
    ss = 1
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)

    f_lane   = F(CJK_B, 40)
    f_lanept = F(LAT_B, 26)
    f_pill   = F(CJK, 30)
    f_pillb  = F(CJK_B, 31)
    f_small  = F(CJK, 26)
    f_tag    = F(CJK_B, 27)
    f_q      = F(LAT_B, 20)

    # ---- lane geometry ----
    top = 150
    lane_h = 520
    gap = 60
    x = 70
    widths = [330, 760, 640, 300]
    cx = []
    for w in widths:
        cx.append((x, x + w))
        x += w + gap

    def lane_header(box, title, sub, color=NAVY):
        x0, y0, x1, y1 = box
        rrect(d, [x0, y0, x1, y0 + 78], 18, fill=color)
        rrect(d, [x0, y0 + 40, x1, y0 + 78], 0, fill=color)  # square bottom of header
        text(d, ((x0 + x1) / 2, y0 + 24), title, f_lane, WHITE, anchor="ma")
        if sub:
            text(d, ((x0 + x1) / 2, y0 + 95 + lane_h), "", f_small, GRAY, anchor="ma")

    # ===== Lane 1: Frontend =====
    x0, x1 = cx[0]
    shadowed_card(img, [x0, top, x1, top + lane_h], 24, PALE)
    rrect(d, [x0, top, x1, top + 84], 24, fill=NAVY)
    rrect(d, [x0, top + 50, x1, top + 84], 0, fill=NAVY)
    text(d, ((x0 + x1) / 2, top + 22), "前端 SPA", f_lane, WHITE, anchor="ma")
    text(d, ((x0 + x1) / 2, top + 110), "Vite + React 18", f_lanept, NAVY, anchor="ma")
    for i, s in enumerate(["Login / 角色", "Analyze 工作台",
                           "DraftEditor 逐句簽核", "Audit 稽核檢視"]):
        yy = top + 165 + i * 82
        rrect(d, [x0 + 28, yy, x1 - 28, yy + 62], 14, fill=WHITE, outline=PALE_LINE, width=2)
        text(d, (x0 + 50, yy + 31), s, f_pill, INK, anchor="lm")
    text(d, ((x0 + x1) / 2, top + lane_h + 28), "Q4 · i18n zh-TW/EN · RWD",
         f_small, GRAY, anchor="ma")

    # ===== Lane 2: Gateway (digiRunner) =====
    x0, x1 = cx[1]
    shadowed_card(img, [x0, top, x1, top + lane_h], 24, (247, 249, 253, 255))
    rrect(d, [x0, top, x1, top + 84], 24, fill=NAVY_DEEP)
    rrect(d, [x0, top + 50, x1, top + 84], 0, fill=NAVY_DEEP)
    text(d, (x0 + 34, top + 22), "Gateway  :8010", f_lane, WHITE, anchor="la")
    text(d, (x1 - 34, top + 30), "digiRunner（厚 Gateway）", f_tag, AMBER, anchor="ra")
    # 6 module pills in 2 rows of 3
    mods = [("Auth", "Q12"), ("RateLimit", "Q18"), ("Mask", "Q3·Q10"),
            ("Cache", "Q9"), ("Orchestrator", "Q1"), ("Audit", "Q13")]
    pw, ph = (x1 - x0 - 34 * 2 - 24 * 2) / 3, 150
    for i, (name, q) in enumerate(mods):
        r, c = divmod(i, 3)
        px0 = x0 + 34 + c * (pw + 24)
        py0 = top + 130 + r * (ph + 28)
        rrect(d, [px0, py0, px0 + pw, py0 + ph], 16, fill=WHITE, outline=PALE_LINE, width=2)
        rrect(d, [px0, py0, px0 + 8, py0 + ph], 0, fill=AMBER)
        text(d, (px0 + 28, py0 + 38), name, f_pillb, NAVY, anchor="lm")
        text(d, (px0 + 28, py0 + 95), q, f_q, GRAY, anchor="lm")
    text(d, ((x0 + x1) / 2, top + lane_h + 28),
         "業務編排 + 安全閘道：稽核 / 限流 / 遮罩 / ACL 集中一處",
         f_small, GRAY, anchor="ma")

    # ===== Lane 3: AI Engine (Dify) =====
    x0, x1 = cx[2]
    shadowed_card(img, [x0, top, x1, top + lane_h], 24, (247, 249, 253, 255))
    rrect(d, [x0, top, x1, top + 84], 24, fill=NAVY)
    rrect(d, [x0, top + 50, x1, top + 84], 0, fill=NAVY)
    text(d, (x0 + 34, top + 22), "AI Engine  :8011", f_lane, WHITE, anchor="la")
    text(d, (x1 - 34, top + 30), "Dify（純推論）", f_tag, AMBER, anchor="ra")
    tools = ["parse_oa  Q11", "retrieve  Q6·Q7", "draft  Q14·Q15",
             "verify_cite  Q14", "deadline  Q17"]
    for i, s in enumerate(tools):
        yy = top + 128 + i * 56
        rrect(d, [x0 + 34, yy, x1 - 34, yy + 46], 12, fill=WHITE, outline=PALE_LINE, width=2)
        text(d, (x0 + 56, yy + 23), s, f_pill, INK, anchor="lm")
    yy = top + 128 + 5 * 56 + 6
    rrect(d, [x0 + 34, yy, x1 - 34, yy + 54], 12, fill=NAVY_LITE)
    text(d, ((x0 + x1) / 2, yy + 27), "llm_client  路由 Q15 + canary Q11",
         f_small, WHITE, anchor="mm")
    text(d, ((x0 + x1) / 2, top + lane_h + 28), "不存任何業務狀態（僅 RAG 向量）",
         f_small, GRAY, anchor="ma")

    # ===== Lane 4: backends =====
    x0, x1 = cx[3]
    for k, (label, sub) in enumerate([("Vector Store", "Qdrant · 租戶隔離 Q7"),
                                      ("LLM", "雲端 / 地端 Q15")]):
        y0 = top + k * 250
        shadowed_card(img, [x0, y0, x1, y0 + 200], 22, WHITE)
        rrect(d, [x0, y0, x1, y0 + 200], 22, fill=None, outline=NAVY, width=3)
        text(d, ((x0 + x1) / 2, y0 + 70), label, f_lanept, NAVY, anchor="mm")
        # split sub into two lines
        text(d, ((x0 + x1) / 2, y0 + 120), sub, f_small, GRAY, anchor="mm")

    # ---- arrows between lanes ----
    def arrow(xa, xb, y, label=None):
        d.line([(xa, y), (xb - 22, y)], fill=NAVY, width=8)
        d.polygon([(xb, y), (xb - 26, y - 16), (xb - 26, y + 16)], fill=NAVY)
        if label:
            text(d, ((xa + xb) / 2, y - 34), label, f_small, GRAY, anchor="mm")

    midy = top + lane_h / 2
    arrow(cx[0][1], cx[1][0], midy, "/api")
    arrow(cx[1][1], cx[2][0], midy, "HTTP · intra-VPC")
    arrow(cx[2][1], cx[3][0], midy)

    # ---- top title strip + invariants footer ----
    text(d, (70, 56), "PatentMind 安全 LLM 管線",
         F(CJK_B, 54), NAVY, anchor="lm")
    text(d, (70, 104), "Gateway 永不直接呼叫 LLM　·　遮罩後才上雲　·　每筆請求一列稽核",
         F(CJK, 30), GRAY, anchor="lm")

    img = img.convert("RGB")
    img.save(os.path.join(ASSETS, "architecture.png"), quality=95)
    print("architecture.png written")


if __name__ == "__main__":
    make()
