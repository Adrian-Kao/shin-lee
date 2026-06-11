"""Full-sheet (全開 787×1092 mm, portrait) poster for PatentMind.

One oversized pptx slide → export to PDF via PowerPoint COM. Text stays
vector (sharp at any print size); the four Pillow diagrams are embedded at
~100–165 effective DPI, fine for poster viewing distance. Same visual
language as build_pptx.py.
"""
import os

from PIL import Image as PILImage
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml import parse_xml
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
DELIVERY_SHOTS = os.path.join(HERE, "..", "docs", "screenshots", "delivery")

NAVY      = RGBColor(0x1E, 0x3A, 0x8A)
NAVY_DEEP = RGBColor(0x12, 0x24, 0x5C)
AMBER     = RGBColor(0xF5, 0xB0, 0x20)
INK       = RGBColor(0x1A, 0x22, 0x36)
GRAY      = RGBColor(0x5A, 0x6B, 0x8C)
HAIR      = RGBColor(0xD7, 0xDD, 0xEA)
WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
PALE      = RGBColor(0xF5, 0xF7, 0xFC)
BLUE_PALE = RGBColor(0xC6, 0xD2, 0xEE)

CJK = "Microsoft JhengHei"

# 全開 787 × 1092 mm = 30.98 × 42.99 in, portrait
SW, SH = 30.98, 42.99

prs = Presentation()
prs.slide_width = Inches(SW)
prs.slide_height = Inches(SH)
s = prs.slides.add_slide(prs.slide_layouts[6])


def set_font(run, name=CJK):
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = parse_xml(
                f'<a:{tag.split(":")[1]} xmlns:a="http://schemas.openxmlformats.org/'
                f'drawingml/2006/main" typeface="{name}"/>')
            rPr.append(el)
        else:
            el.set("typeface", name)


def rect(x, y, w, h, fill, shape=MSO_SHAPE.RECTANGLE):
    sp = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    sp.line.fill.background()
    sp.shadow.inherit = False
    return sp


def txt(x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, leading=1.12):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for i, para_runs in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = leading
        p.space_after = Pt(0)
        for (t, sz, col, bold) in para_runs:
            r = p.add_run()
            r.text = t
            r.font.size = Pt(sz)
            r.font.color.rgb = col
            r.font.bold = bold
            set_font(r)
    return tb


def one(t, sz, col, bold=False):
    return [[(t, sz, col, bold)]]


def pic(path, x, y, w):
    im = PILImage.open(path)
    h = w * im.height / im.width
    s.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
    return h


def kicker(x, y, num, label):
    rect(x, y + 0.12, 0.42, 0.42, AMBER)
    txt(x + 0.7, y, 14, 1.0,
        [[(f"{num} ", 38, AMBER, True), ("· " + label, 38, NAVY, True)]])


MX = 1.2          # page side margin

# ===== banner =====
rect(0, 0, SW, 0.35, AMBER)
rect(0, 0.35, SW, 5.45, NAVY)
logo = PILImage.open(os.path.join(ASSETS, "logo_word_white.png"))
lh = 1.45
s.shapes.add_picture(os.path.join(ASSETS, "logo_word_white.png"),
                     Inches(MX), Inches(0.95),
                     Inches(lh * logo.width / logo.height), Inches(lh))
txt(MX, 2.55, SW - 2 * MX, 1.9, one("專利 OA 答辯自動擬稿系統", 120, WHITE, True))
txt(MX + 0.05, 4.45, SW - 2 * MX, 1.0,
    [[("上傳審查意見書，自動分類核駁理由、檢索前案、產出申復書草稿與法定期限 — ",
       34, BLUE_PALE, False),
      ("機密資料全程不出事務所", 34, AMBER, True)]])

# ===== motivation stats =====
kicker(MX, 6.25, "01", "為什麼需要它 — 案件量在漲，答辯時間沒有變多")
stats = [
    ("71,965", "件/年", "台灣專利申請量（2025）"),
    ("8 個月", "平均", "申請後收到首次 OA"),
    ("2 個月", "法定", "收文後答辯期限"),
    ("4–8 小時", "每案", "人工答辯前置工時"),
]
cw = (SW - 2 * MX - 3 * 0.5) / 4
for i, (num, unit, lab) in enumerate(stats):
    x = MX + i * (cw + 0.5)
    rect(x, 7.35, cw, 2.5, PALE)
    rect(x, 7.35, 0.14, 2.5, AMBER)
    txt(x + 0.5, 7.7, cw - 0.8, 1.2,
        [[(num, 60, NAVY, True), ("　" + unit, 28, AMBER, True)]])
    txt(x + 0.5, 9.0, cw - 0.8, 0.7, one(lab, 24, GRAY))

# ===== architecture =====
kicker(MX, 10.1, "02", "功能模組架構 — 一條安全管線")
aw = 20.0                                # 2400 px / 20 in ≈ 120 dpi
ah = pic(os.path.join(ASSETS, "architecture.png"), (SW - aw) / 2, 11.15, aw)
txt(MX, 11.15 + ah + 0.22, SW - 2 * MX, 0.7,
    [[("兩條鐵則　", 26, AMBER, True),
      ("閘道永不直接呼叫模型；推論引擎不保存任何業務資料。", 25, GRAY, False)]],
    align=PP_ALIGN.CENTER)

# ===== flow_user + flow_data =====
y0 = 19.05
DX = 2.14                                # diagram row side margin
dw = 13.0                                # 2360 px / 13 in ≈ 182 dpi
kicker(MX, y0, "03", "操作流程 × 資料流")
dh = pic(os.path.join(ASSETS, "flow_user.png"), DX, y0 + 1.05, dw)
pic(os.path.join(ASSETS, "flow_data.png"), DX + dw + 0.7, y0 + 1.05, dw)

# ===== flow_ai + trust =====
y1 = y0 + 1.05 + dh + 0.75
kicker(MX, y1, "04", "AI 任務執行流程 × 信任設計")
pic(os.path.join(ASSETS, "flow_ai.png"), DX, y1 + 1.05, dw)
tx = DX + dw + 0.7
trust = [
    ("可逆資料遮罩", "進模型前，當事人、案號先變代碼；對照表只存事務所機器。"),
    ("引證驗證硬牆", "引用逐一比對檢索結果；捏造的直接剝除並標示，不可繞過。"),
    ("不可竄改稽核", "每筆請求一列紀錄、雜湊鏈串接；竄改即現形，一鍵可驗。"),
    ("機密強制地端", "機密案件強制走本地模型；設定錯誤時程式層直接拒絕外送。"),
]
th = (dh - 3 * 0.3) / 4
for i, (h_, b_) in enumerate(trust):
    yy = y1 + 1.05 + i * (th + 0.3)
    rect(tx, yy, dw, th, PALE)
    rect(tx, yy, 0.14, th, NAVY)
    txt(tx + 0.55, yy + 0.15, dw - 1.0, 0.7, one(h_, 30, NAVY, True))
    txt(tx + 0.55, yy + 0.78, dw - 1.0, th - 0.9, one(b_, 22, GRAY), leading=1.2)

# ===== screenshots + verification =====
y2 = y1 + 1.05 + dh + 0.6
kicker(MX, y2, "05", "運行實況 — 真實模型、實機鏈路")
shot_w = 8.0                              # 1440 px / 8 in = 180 dpi
shot_y = y2 + 1.05
sh1 = pic(os.path.join(DELIVERY_SHOTS, "real_05_result_real_qwen.png"),
          DX, shot_y, shot_w)
pic(os.path.join(DELIVERY_SHOTS, "real_08_chain_verified.png"),
    DX + shot_w + 0.5, shot_y, shot_w)
px = DX + 2 * (shot_w + 0.5)
pw = SW - px - DX
rect(px, shot_y, pw, sh1, NAVY_DEEP)
vstats = [("1,232", "後端測試全綠"), ("73", "前端 E2E 全綠"),
          ("25 秒", "實機全鏈路分析"), ("0", "機密外送事件")]
vh = sh1 / 4
for i, (num, lab) in enumerate(vstats):
    yy = shot_y + i * vh
    txt(px + 0.7, yy + vh * 0.14, pw - 1.2, 0.8, one(num, 40, AMBER, True))
    txt(px + 0.7, yy + vh * 0.60, pw - 1.2, 0.5, one(lab, 21, BLUE_PALE))
cap_y = shot_y + sh1 + 0.12
txt(DX, cap_y, shot_w, 0.45,
    one("qwen2.5:7b 正確抓出請求項 9 缺先行詞，產出繁中草稿", 18, GRAY))
txt(DX + shot_w + 0.5, cap_y, shot_w, 0.45,
    one("稽核鏈一鍵驗證：29 筆紀錄 0 不一致，竄改即現形", 18, GRAY))

# ===== footer =====
fy = SH - 1.45
rect(0, fy, SW, 1.45, NAVY)
txt(MX, fy + 0.42, SW - 2 * MX, 0.7,
    [[("實機整合 TPIsoftware digiRunner × Dify　·　本地模型 qwen2.5:7b　·　",
       28, BLUE_PALE, False),
      ("NCCU GDGoC × Computex 2026　|　PatentMind AI", 28, WHITE, True)]],
    align=PP_ALIGN.CENTER)

out = os.path.join(HERE, "PatentMind_海報_全開.pptx")
prs.save(out)
print("saved poster pptx:", out)
