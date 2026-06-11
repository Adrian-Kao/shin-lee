"""Architecture diagram for PatentMind, drawn with Pillow.

Real delivery pipeline (2026-06):
  前端 SPA -> digiRunner :18080 -> Gateway :8010 -> AI Engine :8011 -> Dify :8088 -> Ollama
Custom-drawn so it reads as designed, not a slide full of default boxes.
"""
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

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
    W, H = 2400, 810
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)

    f_lane   = F(CJK_B, 36)
    f_lanept = F(CJK_B, 24)
    f_pill   = F(CJK, 27)
    f_pillb  = F(CJK_B, 28)
    f_small  = F(CJK, 25)
    f_tag    = F(CJK_B, 24)

    # ---- lane geometry: 5 lanes ----
    top = 170
    lane_h = 520
    gap = 56
    x = 64
    widths = [270, 330, 640, 540, 300]
    cx = []
    for w in widths:
        cx.append((x, x + w))
        x += w + gap

    def lane_head(x0, x1, label, sub_label, color):
        rrect(d, [x0, top, x1, top + 80], 22, fill=color)
        rrect(d, [x0, top + 46, x1, top + 80], 0, fill=color)
        text(d, ((x0 + x1) / 2, top + 20), label, f_lane, WHITE, anchor="ma")
        if sub_label:
            text(d, ((x0 + x1) / 2, top + 96), sub_label, f_lanept, NAVY, anchor="ma")

    # ===== Lane 1: Frontend =====
    x0, x1 = cx[0]
    shadowed_card(img, [x0, top, x1, top + lane_h], 24, PALE)
    lane_head(x0, x1, "前端 SPA", "React + Vite", NAVY)
    for i, s in enumerate(["登入 / 角色", "分析工作台", "逐句簽核", "稽核檢視"]):
        yy = top + 168 + i * 80
        rrect(d, [x0 + 24, yy, x1 - 24, yy + 60], 14, fill=WHITE, outline=PALE_LINE, width=2)
        text(d, (x0 + 44, yy + 30), s, f_pill, INK, anchor="lm")
    text(d, ((x0 + x1) / 2, top + lane_h + 28), "繁中 / 英文 · RWD",
         f_small, GRAY, anchor="ma")

    # ===== Lane 2: digiRunner =====
    x0, x1 = cx[1]
    shadowed_card(img, [x0, top, x1, top + lane_h], 24, (247, 249, 253, 255))
    lane_head(x0, x1, "digiRunner", ":18080 前線 API 閘道", NAVY_DEEP)
    for i, s in enumerate(["路由 / 反向代理", "身分標頭轉發", "流量治理", "企業 SSO 介接"]):
        yy = top + 168 + i * 80
        rrect(d, [x0 + 24, yy, x1 - 24, yy + 60], 14, fill=WHITE, outline=PALE_LINE, width=2)
        rrect(d, [x0 + 24, yy, x0 + 32, yy + 60], 0, fill=AMBER)
        text(d, (x0 + 52, yy + 30), s, f_pill, INK, anchor="lm")
    text(d, ((x0 + x1) / 2, top + lane_h + 28), "TPIsoftware 開源版 · 實機部署",
         f_small, GRAY, anchor="ma")

    # ===== Lane 3: Gateway =====
    x0, x1 = cx[2]
    shadowed_card(img, [x0, top, x1, top + lane_h], 24, (247, 249, 253, 255))
    lane_head(x0, x1, "安全業務閘道  :8010", None, NAVY_DEEP)
    mods = [("身分與權限", "JWT · 案件 ACL"), ("限流與配額", "成本斷路器"),
            ("資料遮罩", "PII · 客戶詞庫"), ("快取", "租戶隔離"),
            ("流程編排", "六步業務管線"), ("稽核", "append-only 鏈")]
    pw, ph = (x1 - x0 - 30 * 2 - 20 * 2) / 3, 150
    for i, (name, subt) in enumerate(mods):
        r, c = divmod(i, 3)
        px0 = x0 + 30 + c * (pw + 20)
        py0 = top + 124 + r * (ph + 26)
        rrect(d, [px0, py0, px0 + pw, py0 + ph], 16, fill=WHITE, outline=PALE_LINE, width=2)
        rrect(d, [px0, py0, px0 + 8, py0 + ph], 0, fill=AMBER)
        text(d, (px0 + 26, py0 + 42), name, f_pillb, NAVY, anchor="lm")
        text(d, (px0 + 26, py0 + 100), subt, f_small, GRAY, anchor="lm")
    text(d, ((x0 + x1) / 2, top + lane_h + 28),
         "遮罩後才送推論 · 每筆請求一列稽核 · 機密案件強制地端",
         f_small, GRAY, anchor="ma")

    # ===== Lane 4: AI Engine =====
    x0, x1 = cx[3]
    shadowed_card(img, [x0, top, x1, top + lane_h], 24, (247, 249, 253, 255))
    lane_head(x0, x1, "AI 推論引擎  :8011", None, NAVY)
    tools = ["核駁理由解析", "前案檢索 RAG", "申復書草擬", "引證驗證（硬牆）", "期限試算"]
    for i, s in enumerate(tools):
        yy = top + 124 + i * 56
        rrect(d, [x0 + 30, yy, x1 - 30, yy + 46], 12, fill=WHITE, outline=PALE_LINE, width=2)
        text(d, (x0 + 52, yy + 23), s, f_pill, INK, anchor="lm")
    yy = top + 124 + 5 * 56 + 8
    rrect(d, [x0 + 30, yy, x1 - 30, yy + 54], 12, fill=NAVY_LITE)
    text(d, ((x0 + x1) / 2, yy + 27), "多模型路由（mock / 雲端 / 地端 / Dify）",
         f_small, WHITE, anchor="mm")
    text(d, ((x0 + x1) / 2, top + lane_h + 28), "不存任何業務狀態",
         f_small, GRAY, anchor="ma")

    # ===== Lane 5: Dify + 地端模型 =====
    x0, x1 = cx[4]
    cards = [("Dify CE  :8088", "AI workflow 編排\n（實機部署）"),
             ("Ollama 地端模型", "qwen2.5:7b\n機密不出機器")]
    for k, (label, sub) in enumerate(cards):
        y0 = top + k * 270
        shadowed_card(img, [x0, y0, x1, y0 + 230], 22, WHITE)
        rrect(d, [x0, y0, x1, y0 + 230], 22, fill=None, outline=NAVY, width=3)
        text(d, ((x0 + x1) / 2, y0 + 56), label, f_tag, NAVY, anchor="mm")
        for j, line in enumerate(sub.split("\n")):
            text(d, ((x0 + x1) / 2, y0 + 120 + j * 44), line, f_small, GRAY, anchor="mm")
    # vertical connector Dify -> Ollama
    midx = (x0 + x1) / 2
    d.line([(midx, top + 230), (midx, top + 270 - 22)], fill=NAVY, width=8)
    d.polygon([(midx, top + 270), (midx - 14, top + 270 - 24), (midx + 14, top + 270 - 24)],
              fill=NAVY)

    # ---- arrows between lanes ----
    def arrow(xa, xb, y, label=None):
        d.line([(xa, y), (xb - 22, y)], fill=NAVY, width=8)
        d.polygon([(xb, y), (xb - 26, y - 16), (xb - 26, y + 16)], fill=NAVY)
        if label:
            text(d, ((xa + xb) / 2, y - 34), label, f_small, GRAY, anchor="mm")

    midy = top + lane_h / 2
    arrow(cx[0][1], cx[1][0], midy)
    arrow(cx[1][1], cx[2][0], midy)
    arrow(cx[2][1], cx[3][0], midy)
    arrow(cx[3][1], cx[4][0], top + 115 + 110)

    # ---- top title strip ----
    text(d, (64, 52), "從上傳 OA 到申復書草稿：一條安全管線",
         F(CJK_B, 52), NAVY, anchor="lm")
    text(d, (64, 110), "閘道永不直接呼叫模型　·　遮罩後才送推論　·　每筆請求一列稽核",
         F(CJK, 30), GRAY, anchor="lm")

    img = img.convert("RGB")
    img.save(os.path.join(ASSETS, "architecture.png"), quality=95)
    print("architecture.png written")


if __name__ == "__main__":
    make()
