"""Full-sheet (全開 787×1092 mm, portrait) poster for PatentMind — v2.

Poster-native design (not slides-on-paper): decorative Pillow background
(gradient, diagonal bands, rings, glows), diagrams embedded WITHOUT their
slide titles (cropped) inside white cards with amber pill labels, tilted
live screenshots, an ALL-GREEN badge. All text stays vector → export to
PDF via PowerPoint COM prints sharp at any size.
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
BLUE_PALE = RGBColor(0xC6, 0xD2, 0xEE)

CJK = "Microsoft JhengHei"
SW, SH = 30.98, 42.99            # 787 × 1092 mm
MX = 1.2

prs = Presentation()
prs.slide_width = Inches(SW)
prs.slide_height = Inches(SH)
s = prs.slides.add_slide(prs.slide_layouts[6])

_tmp_files = []


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


def add_shadow(shape, blur=110000, dist=42000, alpha=24000):
    spPr = shape._element.spPr
    # shadow.inherit=False leaves an empty <a:effectLst/> behind — a second
    # one corrupts the file for PowerPoint, so replace instead of append.
    for el in spPr.findall(qn("a:effectLst")):
        spPr.remove(el)
    xml = (f'<a:effectLst xmlns:a="http://schemas.openxmlformats.org/'
           f'drawingml/2006/main"><a:outerShdw blurRad="{blur}" dist="{dist}" '
           f'dir="5400000" rotWithShape="0"><a:srgbClr val="1A2236">'
           f'<a:alpha val="{alpha}"/></a:srgbClr></a:outerShdw></a:effectLst>')
    spPr.append(parse_xml(xml))


def shape(x, y, w, h, fill=None, line=None, line_w=2.0, kind=MSO_SHAPE.RECTANGLE,
          shadow=False, round_=0.08, rot=0.0):
    sp = s.shapes.add_shape(kind, Inches(x), Inches(y), Inches(w), Inches(h))
    if kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        sp.adjustments[0] = round_
    if fill is None:
        sp.fill.background()
    else:
        sp.fill.solid()
        sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(line_w)
    sp.shadow.inherit = False
    if shadow:
        add_shadow(sp)
    if rot:
        sp.rotation = rot
    return sp


def txt(x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
        leading=1.12, rot=0.0):
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
    if rot:
        tb.rotation = rot
    return tb


def one(t, sz, col, bold=False):
    return [[(t, sz, col, bold)]]


def plain_crop(name, crop_top):
    """Diagram minus its built-in title strip → temp png."""
    src = os.path.join(ASSETS, f"{name}.png")
    out = os.path.join(HERE, f"_tmp_plain_{name}.png")
    with PILImage.open(src) as im:
        im.crop((0, crop_top, im.width, im.height)).save(out)
    _tmp_files.append(out)
    return out


def pic(path, x, y, w, shadow=True, rot=0.0):
    with PILImage.open(path) as im:
        h = w * im.height / im.width
    p = s.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))
    p.shadow.inherit = False
    if shadow:
        add_shadow(p)
    if rot:
        p.rotation = rot
    return h


def pill(x, y, w, h, text_, sz, fg, bg=None, line=None, bold=True, shadow=False):
    shape(x, y, w, h, fill=bg, line=line, line_w=2.25,
          kind=MSO_SHAPE.ROUNDED_RECTANGLE, round_=0.5, shadow=shadow)
    txt(x, y, w, h, one(text_, sz, fg, bold),
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def sec(num, title_, y):
    shape(MX, y, 0.66, 0.66, fill=AMBER, kind=MSO_SHAPE.OVAL, shadow=True)
    txt(MX, y + 0.02, 0.66, 0.62, one(num, 27, WHITE, True),
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    txt(MX + 0.95, y - 0.06, 24, 0.85, one(title_, 42, NAVY, True))
    shape(MX + 0.98, y + 0.86, 1.7, 0.075, fill=AMBER)


# ===================== background art =====================
s.shapes.add_picture(os.path.join(ASSETS, "poster_bg.png"),
                     0, 0, Inches(SW), Inches(SH))

# ===================== banner =====================
with PILImage.open(os.path.join(ASSETS, "logo_word_white.png")) as logo:
    logo_ar = logo.width / logo.height
lh = 1.3
s.shapes.add_picture(os.path.join(ASSETS, "logo_word_white.png"),
                     Inches(MX), Inches(0.78),
                     Inches(lh * logo_ar), Inches(lh))
txt(MX, 2.25, SW - 2 * MX, 2.0, one("專利 OA 答辯自動擬稿系統", 126, WHITE, True))
txt(MX + 0.05, 4.32, 24.5, 1.0,
    [[("上傳審查意見書，AI 分類核駁、檢索前案、產出申復書草稿與法定期限　—　",
       31, BLUE_PALE, False),
      ("機密資料全程不出事務所", 31, AMBER, True)]])
chips = ["可逆遮罩", "引證驗證硬牆", "不可竄改稽核", "機密強制地端"]
cx = MX + 0.05
for c in chips:
    w = 0.9 + len(c) * 0.42
    pill(cx, 5.3, w, 0.66, c, 23, AMBER, bg=None, line=AMBER)
    cx += w + 0.42

# ===================== 01 動機 =====================
sec("01", "案件量在漲，答辯時間沒有變多", 7.6)
stats = [
    ("71,965", "件/年", "台灣專利申請量（2025）"),
    ("8 個月", "平均", "申請後收到首次 OA"),
    ("2 個月", "法定", "收文後答辯期限"),
    ("4–8 小時", "每案", "人工答辯前置工時"),
]
cw = (SW - 2 * MX - 3 * 0.4) / 4
for i, (num, unit, lab) in enumerate(stats):
    x = MX + i * (cw + 0.4)
    shape(x + 0.04, 8.72, 0.3, 0.12, fill=AMBER)
    txt(x, 8.98, cw - 0.2, 1.25,
        [[(num, 72, NAVY, True), ("　" + unit, 26, AMBER, True)]])
    txt(x + 0.04, 10.25, cw - 0.3, 0.6, one(lab, 23, GRAY))
    if i:
        shape(x - 0.22, 8.8, 0.022, 2.05, fill=HAIR)
txt(MX, 11.05, SW - 2 * MX, 0.6,
    [[("為什麼不直接貼 ChatGPT？　", 24, NAVY, True),
      ("機密外洩 · 捏造引用 · 無稽核紀錄 · 期限算錯不可復原 — 所以需要一座有護欄的系統。",
       23, GRAY, False)]])

# ===================== 02 功能模組架構 =====================
sec("02", "功能模組架構 — 一條安全管線", 11.7)
arch = plain_crop("architecture", 135)
card_x, card_y, card_w = 1.0, 12.55, SW - 2.0
img_w = 21.0
with PILImage.open(arch) as ih:
    img_h = img_w * ih.height / ih.width
card_h = 0.45 + img_h + 0.55 + 0.25
shape(card_x, card_y, card_w, card_h, fill=WHITE,
      kind=MSO_SHAPE.ROUNDED_RECTANGLE, round_=0.045, shadow=True)
pic(arch, (SW - img_w) / 2, card_y + 0.45, img_w, shadow=False)
txt(card_x, card_y + 0.45 + img_h + 0.15, card_w, 0.55,
    [[("兩條鐵則　", 24, AMBER, True),
      ("閘道永不直接呼叫模型；推論引擎不保存任何業務資料。", 23, GRAY, False)]],
    align=PP_ALIGN.CENTER)
y_after_02 = card_y + card_h

# ===================== 03 操作流程 × 資料流 =====================
y0 = y_after_02 + 0.4
sec("03", "操作流程 × 資料流", y0)
DX = 1.0
cardw = (SW - 2 * DX - 0.7) / 2
imw = 11.6                       # 2360 px / 11.6 in ≈ 203 dpi
flows = [("flow_user", "操作流程｜使用者只做 4 件事"),
         ("flow_data", "資料流｜每一步都知道資料在誰手上")]
fy = y0 + 1.05
fh = None
for i, (name, label) in enumerate(flows):
    p = plain_crop(name, 148)
    with PILImage.open(p) as im:
        imh = imw * im.height / im.width
    ch = 0.55 + imh + 0.4
    x = DX + i * (cardw + 0.7)
    shape(x, fy, cardw, ch, fill=WHITE,
          kind=MSO_SHAPE.ROUNDED_RECTANGLE, round_=0.05, shadow=True)
    pic(p, x + (cardw - imw) / 2, fy + 0.5, imw, shadow=False)
    pill(x + 0.55, fy - 0.33, 0.62 + len(label) * 0.42, 0.66, label, 22,
         WHITE, bg=NAVY, shadow=True)
    fh = ch

# ===================== 04 AI 任務流程 × 信任設計 =====================
y1 = fy + fh + 0.6
sec("04", "AI 任務執行流程 × 信任設計", y1)
ty = y1 + 1.05
p = plain_crop("flow_ai", 148)
with PILImage.open(p) as im:
    imh = imw * im.height / im.width
ch = 0.55 + imh + 0.4
shape(DX, ty, cardw, ch, fill=WHITE,
      kind=MSO_SHAPE.ROUNDED_RECTANGLE, round_=0.05, shadow=True)
pic(p, DX + (cardw - imw) / 2, ty + 0.5, imw, shadow=False)
pill(DX + 0.55, ty - 0.33, 0.62 + 17 * 0.42, 0.66,
     "AI 流程｜先舉證、再下筆、寫完還要驗", 22, WHITE, bg=NAVY, shadow=True)

trust = [
    ("可逆資料遮罩", "進模型前當事人、案號先變代碼；對照表只存事務所機器。"),
    ("引證驗證硬牆", "引用逐一比對檢索結果；捏造的直接剝除標示，不可繞過。"),
    ("不可竄改稽核", "每筆請求一列紀錄、雜湊鏈串接；竄改即現形，一鍵可驗。"),
    ("機密強制地端", "機密案件強制走本地模型；設錯時程式層直接拒絕外送。"),
]
tx0 = DX + cardw + 0.7
chip_w = (cardw - 0.42) / 2
chip_h = (ch - 0.42) / 2
for i, (h_, b_) in enumerate(trust):
    r, c = divmod(i, 2)
    x = tx0 + c * (chip_w + 0.42)
    y = ty + r * (chip_h + 0.42)
    shape(x, y, chip_w, chip_h, fill=WHITE,
          kind=MSO_SHAPE.ROUNDED_RECTANGLE, round_=0.10, shadow=True)
    shape(x + 0.42, y + 0.42, 0.56, 0.56, fill=AMBER, kind=MSO_SHAPE.OVAL)
    txt(x + 0.42, y + 0.43, 0.56, 0.54, one("✓", 24, WHITE, True),
        align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    txt(x + 1.2, y + 0.42, chip_w - 1.5, 0.6, one(h_, 28, NAVY, True))
    txt(x + 0.45, y + 1.18, chip_w - 0.9, chip_h - 1.4, one(b_, 21, GRAY),
        leading=1.22)

# ===================== 05 運行實況 =====================
y2 = ty + ch + 0.6
sec("05", "運行實況 — 真實模型、實機鏈路", y2)
sy = y2 + 1.25
shot_h = 3.9
shot_w = shot_h * 1440 / 900
shots = [
    ("real_05_result_real_qwen.png", -1.4,
     "qwen2.5:7b 正確抓出請求項 9 缺先行詞"),
    ("real_08_chain_verified.png", 1.4,
     "稽核鏈一鍵驗證：29 筆紀錄 0 不一致"),
]
for i, (f, rot, cap) in enumerate(shots):
    x = DX + i * (shot_w + 0.55)
    pic(os.path.join(DELIVERY_SHOTS, f), x, sy, shot_w, shadow=True, rot=rot)
    pill(x + 0.45, sy + shot_h - 0.28, shot_w - 0.9, 0.58, cap, 17,
         NAVY, bg=WHITE, shadow=True)
px = DX + 2 * (shot_w + 0.55) + 0.25
pw = SW - px - DX
shape(px, sy, pw, shot_h, fill=NAVY_DEEP,
      kind=MSO_SHAPE.ROUNDED_RECTANGLE, round_=0.07, shadow=True)
vstats = [("1,232", "後端測試全綠"), ("73", "前端 E2E 全綠"),
          ("25 秒", "實機全鏈路分析"), ("0", "機密外送事件")]
vw = (pw - 1.2) / 4
for i, (num, lab) in enumerate(vstats):
    x = px + 0.6 + i * vw
    txt(x, sy + 1.0, vw - 0.2, 1.0, one(num, 44, AMBER, True),
        align=PP_ALIGN.CENTER)
    txt(x, sy + 2.15, vw - 0.2, 0.6, one(lab, 19, BLUE_PALE),
        align=PP_ALIGN.CENTER)
badge = 1.65
shape(px + pw - 1.25, sy - 0.7, badge, badge, fill=AMBER,
      kind=MSO_SHAPE.OVAL, shadow=True, rot=-10)
txt(px + pw - 1.25, sy - 0.62, badge, badge,
    [[("ALL", 22, NAVY_DEEP, True)], [("GREEN", 22, NAVY_DEEP, True)]],
    align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, rot=-10)

# ===================== footer =====================
txt(MX, SH - 1.05, SW - 2 * MX, 0.7,
    [[("實機整合 TPIsoftware digiRunner × Dify　·　本地模型 qwen2.5:7b　·　",
       27, BLUE_PALE, False),
      ("NCCU GDGoC × Computex 2026　|　PatentMind AI", 27, WHITE, True)]],
    align=PP_ALIGN.CENTER)

out = os.path.join(HERE, "PatentMind_海報_全開.pptx")
prs.save(out)
for f in _tmp_files:
    try:
        os.remove(f)
    except OSError:
        pass
print("saved poster pptx:", out, f"(content ends ≈ {sy + shot_h:.2f} in)")
