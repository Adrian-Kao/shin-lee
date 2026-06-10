# -*- coding: utf-8 -*-
"""Build the PatentMind presentation (Traditional Chinese, 16:9).

Editorial style: big type, accent bars, generous whitespace, custom artwork.
Deliberately avoids the "grid of boxes" look. Embeds the logo, a custom
architecture diagram, and four real frontend screenshots with annotations.
"""
import os
from PIL import Image as PILImage
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pptx.oxml.ns import qn
from pptx.oxml import parse_xml

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")
SHOTS = os.path.join(HERE, "..", "frontend", "tests", "e2e",
                     "__screenshots__", "visual_regression.spec.js")
DELIVERY_SHOTS = os.path.join(HERE, "..", "docs", "screenshots", "delivery")

# ---- palette ----
NAVY      = RGBColor(0x1E, 0x3A, 0x8A)
NAVY_DEEP = RGBColor(0x12, 0x24, 0x5C)
NAVY_GHOST= RGBColor(0x2A, 0x49, 0x9A)
AMBER     = RGBColor(0xF5, 0xB0, 0x20)
INK       = RGBColor(0x1A, 0x22, 0x36)
GRAY      = RGBColor(0x5A, 0x6B, 0x8C)
LGRAY     = RGBColor(0x8A, 0x97, 0xB2)
HAIR      = RGBColor(0xD7, 0xDD, 0xEA)
GHOST     = RGBColor(0xEE, 0xF1, 0xF8)
WHITE     = RGBColor(0xFF, 0xFF, 0xFF)
PALE      = RGBColor(0xF5, 0xF7, 0xFC)

CJK = "Microsoft JhengHei"

SW, SH = 13.333, 7.5

prs = Presentation()
prs.slide_width = Inches(SW)
prs.slide_height = Inches(SH)
BLANK = prs.slide_layouts[6]

_page = 0


# ----------------- low-level helpers -----------------
def set_font(run, name=CJK):
    run.font.name = name
    rPr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        el = rPr.find(qn(tag))
        if el is None:
            el = parse_xml(
                '<a:%s xmlns:a="http://schemas.openxmlformats.org/'
                'drawingml/2006/main" typeface="%s"/>' % (tag.split(":")[1], name))
            rPr.append(el)
        else:
            el.set("typeface", name)


def slide(bg=WHITE):
    s = prs.slides.add_slide(BLANK)
    rect(s, 0, 0, SW, SH, bg)
    return s


def rect(s, x, y, w, h, fill, line=None, line_w=1.0, shape=MSO_SHAPE.RECTANGLE):
    sp = s.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    sp.fill.solid()
    sp.fill.fore_color.rgb = fill
    if line is None:
        sp.line.fill.background()
    else:
        sp.line.color.rgb = line
        sp.line.width = Pt(line_w)
    sp.shadow.inherit = False
    return sp


def hline(s, x, y, w, color=HAIR, weight=1.0):
    ln = s.shapes.add_connector(2, Inches(x), Inches(y), Inches(x + w), Inches(y))
    ln.line.color.rgb = color
    ln.line.width = Pt(weight)
    return ln


def txt(s, x, y, w, h, runs, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP,
        leading=1.12, space_after=6):
    """runs: list of paragraphs; each paragraph is list of (text,size,color,bold)."""
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for i, para in enumerate(runs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = leading
        p.space_after = Pt(space_after)
        p.space_before = Pt(0)
        for (t, sz, col, bold) in para:
            r = p.add_run()
            r.text = t
            r.font.size = Pt(sz)
            r.font.color.rgb = col
            r.font.bold = bold
            set_font(r)
    return tb


def para(t, sz, col, bold=False):
    """a single paragraph = list of one run-tuple."""
    return [(t, sz, col, bold)]


def one(t, sz, col, bold=False):
    """a full runs arg = list of one paragraph."""
    return [[(t, sz, col, bold)]]


def pic_shadow(shape):
    spPr = shape._element.spPr
    xml = ('<a:effectLst xmlns:a="http://schemas.openxmlformats.org/'
           'drawingml/2006/main"><a:outerShdw blurRad="90000" dist="38100" '
           'dir="5400000" rotWithShape="0"><a:srgbClr val="1A2236">'
           '<a:alpha val="26000"/></a:srgbClr></a:outerShdw></a:effectLst>')
    spPr.append(parse_xml(xml))


def add_pic_fitw(s, path, x, y, w):
    im = PILImage.open(path)
    ar = im.height / im.width
    p = s.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(w * ar))
    pic_shadow(p)
    return p, w * ar


def add_pic_fith(s, path, x, y, h):
    im = PILImage.open(path)
    ar = im.width / im.height
    p = s.shapes.add_picture(path, Inches(x), Inches(y), Inches(h * ar), Inches(h))
    pic_shadow(p)
    return p, h * ar


def footer(s, dark=False):
    global _page
    _page += 1
    c = LGRAY if not dark else RGBColor(0x8D, 0x9C, 0xC4)
    txt(s, 0.9, 7.06, 9, 0.3,
        one("PatentMind AI　·　NCCU GDGoC × Computex 2026", 10, c))
    txt(s, SW - 1.7, 7.06, 0.8, 0.3, one("%02d" % _page, 10, c),
        align=PP_ALIGN.RIGHT)


def kicker(s, num, label):
    """small amber square + '03 · 動機' kicker line."""
    rect(s, 0.9, 0.72, 0.16, 0.16, AMBER)
    txt(s, 1.18, 0.62, 9, 0.4,
        [[("%s " % num, 14, AMBER, True), ("· " + label, 14, GRAY, False)]])


def title(s, text, y=1.0):
    txt(s, 0.88, y, 11.5, 1.0, one(text, 33, NAVY, True))
    hline(s, 0.9, y + 0.92, 11.55, HAIR, 1.2)


def ghost_num(s, n):
    txt(s, SW - 4.3, 0.2, 4.2, 2.6, one(n, 150, GHOST, True),
        align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.TOP)


def bullets(s, x, y, w, items, gap=0.10, size=16, lead_size=None):
    """items: list of (level, text, qtag|None)."""
    cur = y
    for (lvl, text, qtag) in items:
        if lvl == 0:
            rect(s, x, cur + 0.085, 0.13, 0.13, AMBER)
            tx = x + 0.32
            sz = size
            col = INK
            bold = False
        else:
            rect(s, x + 0.42, cur + 0.10, 0.10, 0.10, NAVY, shape=MSO_SHAPE.OVAL)
            tx = x + 0.74
            sz = size - 2
            col = GRAY
            bold = False
        para = [(text, sz, col, bold)]
        if qtag:
            para.append(("　" + qtag, sz - 3, AMBER, True))
        tb = txt(s, tx, cur, w - (tx - x), 0.8, [para], leading=1.1, space_after=0)
        # estimate height for next line
        import math
        approx_chars = max(1, int((w - (tx - x)) / (sz / 72 * 1.0)))
        lines = max(1, math.ceil(len(text) / approx_chars))
        cur += 0.30 * (sz / 16) * lines + gap
    return cur


# ----------------- slide builders -----------------
def s_title():
    s = slide(NAVY)
    rect(s, 0, 0, SW, 0.16, AMBER)          # top accent
    add_pic_fith(s, os.path.join(ASSETS, "logo_word_white.png"), 0.95, 1.05, 1.1)
    txt(s, 0.95, 2.8, 11.6, 1.6,
        one("專利 OA 答辯自動擬稿系統", 46, WHITE, True))
    txt(s, 0.97, 3.95, 11.5, 1.4,
        [[("上傳審查意見書,自動分類核駁理由、檢索前案、產出申復書草稿與法定期限 — ",
           18, RGBColor(0xC6,0xD2,0xEE), False),
          ("機密資料全程不出事務所", 18, AMBER, True)]], leading=1.3)
    hline(s, 0.97, 5.15, 5.2, RGBColor(0x3B,0x55,0x9E), 1.2)
    txt(s, 0.97, 5.35, 11.3, 0.5,
        one("實機整合 TPIsoftware digiRunner × Dify　·　全鏈路 28 秒　·　1,232 項測試綠燈",
            14, RGBColor(0x9D, 0xAC, 0xD4)))
    txt(s, 0.97, 6.55, 11, 0.4,
        one("NCCU GDGoC × Computex 2026　|　PatentMind AI", 13,
            RGBColor(0x8D,0x9C,0xC4)))


def s_agenda():
    s = slide()
    kicker(s, "00", "Agenda")
    title(s, "簡報大綱")
    items = [
        ("1", "題目說明", "這個系統做什麼"),
        ("2", "動機", "為什麼值得做"),
        ("3", "系統怎麼運作", "架構與信任設計"),
        ("4", "產品畫面", "三個關鍵畫面"),
        ("5", "平台整合實證", "digiRunner × Dify 實機"),
        ("6", "現況與 Demo", "驗證數字 + 現場操作"),
    ]
    x0, y0 = 1.0, 2.35
    colw = 5.9
    for i, (n, t, sub) in enumerate(items):
        col = i // 3
        row = i % 3
        x = x0 + col * (colw + 0.5)
        y = y0 + row * 1.35
        txt(s, x, y - 0.02, 0.8, 0.8, one(n, 30, AMBER, True))
        txt(s, x + 0.7, y + 0.02, colw - 0.7, 0.5, one(t, 19, INK, True))
        txt(s, x + 0.7, y + 0.46, colw - 0.7, 0.4, one(sub, 12.5, GRAY))
    footer(s)


def s_topic():
    s = slide()
    kicker(s, "01", "題目說明")
    title(s, "把答辯前置工作,從一個下午壓到一杯咖啡")
    ghost_num(s, "01")
    txt(s, 0.9, 2.1, 11.5, 0.75,
        [[("背景：", 16, NAVY, True),
          ("專利申請後,審查官常以「審查意見通知函(Office Action)」核駁部分請求項;"
           "事務所必須在法定期限內逐點答辯,否則申請失效。", 16, INK, False)]],
        leading=1.3)
    txt(s, 0.9, 3.0, 11.5, 0.5,
        [[("本系統：", 16, NAVY, True),
          ("讀懂 OA、找好證據、寫出草稿 — 律師只需審閱與定稿。", 16, INK, False)]],
        leading=1.3)
    steps = [
        ("上傳 OA", ["PDF / 文字", "自動萃取"]),
        ("分類核駁", ["新穎性 / 進步性", "/ 明確性…"]),
        ("檢索證據", ["本案請求項", "+ 前案文獻"]),
        ("產出草稿", ["申復書草稿", "+ 法定期限"]),
        ("律師簽核", ["逐句確認", "才可匯出"]),
    ]
    x0, y0, cw, ch, gp = 0.95, 3.85, 2.12, 1.78, 0.22
    for i, (h, blines) in enumerate(steps):
        x = x0 + i * (cw + gp)
        rect(s, x, y0, cw, ch, PALE if i < 4 else GHOST)
        rect(s, x, y0, cw, 0.10, AMBER if i < 4 else NAVY)
        txt(s, x + 0.16, y0 + 0.24, cw - 0.3, 0.45,
            [[("%d " % (i + 1), 16, AMBER, True), (h, 16, NAVY, True)]])
        txt(s, x + 0.16, y0 + 0.82, cw - 0.3, 0.85,
            [para(l, 12, GRAY) for l in blines], leading=1.15, space_after=2)
        if i < 4:
            txt(s, x + cw - 0.02, y0 + 0.66, gp + 0.06, 0.5,
                one("→", 15, LGRAY, True), align=PP_ALIGN.CENTER)
    txt(s, 0.9, 6.0, 11.5, 0.7,
        [[("定位：自動「擬稿」系統 — ", 15.5, NAVY, True),
          ("AI 負責起草與舉證,律師負責判斷與簽核;沒有簽核,系統拒絕匯出。",
           15.5, INK, False)]], leading=1.3)
    footer(s)


def s_motivation():
    s = slide()
    kicker(s, "02", "動機")
    title(s, "案件量在漲,答辯時間沒有變多")
    ghost_num(s, "02")
    stats = [
        ("71,965", "件/年", "台灣專利申請量(2025)"),
        ("8 個月", "平均", "申請後收到首次 OA"),
        ("2 個月", "法定", "收文後答辯期限"),
        ("4–8 小時", "每案", "人工答辯前置工時"),
    ]
    x0, y0, cw = 0.95, 2.3, 2.78
    for i, (num, unit, lab) in enumerate(stats):
        x = x0 + i * (cw + 0.12)
        rect(s, x, y0, cw, 1.62, PALE)
        rect(s, x, y0, 0.07, 1.62, AMBER)
        txt(s, x + 0.24, y0 + 0.18, cw - 0.4, 0.62,
            [[(num, 27, NAVY, True), ("　" + unit, 13, AMBER, True)]])
        txt(s, x + 0.24, y0 + 0.95, cw - 0.4, 0.55, one(lab, 12.5, GRAY), leading=1.15)
    txt(s, 0.9, 4.35, 11.5, 0.5,
        one("結果:資深律師時間被重複性前置工作吃掉,品質風險上升。", 15.5, INK))
    hline(s, 0.9, 5.0, 11.55, HAIR, 1.2)
    txt(s, 0.9, 5.18, 11.5, 0.45,
        one("那為什麼不直接貼進 ChatGPT?", 16, NAVY, True))
    risks = [
        ("機密外洩", "客戶案件進了公有模型"),
        ("捏造引用", "編造判例 = 專業責任事故"),
        ("無稽核", "事後無法證明誰看過什麼"),
        ("期限風險", "算錯法定期日不可復原"),
    ]
    for i, (h, b) in enumerate(risks):
        x = 0.95 + i * 2.9
        txt(s, x, 5.72, 2.7, 0.4, [[("✕ ", 14, AMBER, True), (h, 14.5, NAVY, True)]])
        txt(s, x, 6.12, 2.7, 0.6, one(b, 12, GRAY), leading=1.15)
    footer(s)


def s_solution():
    s = slide()
    kicker(s, "03", "系統怎麼運作")
    title(s, "AI 起草,律師定稿")
    ghost_num(s, "03")
    cards = [
        ("自動分類核駁理由", "中文 / 英文 OA 都能讀;新穎性、進步性、明確性、缺先行詞等逐項拆解,標示受影響的請求項。"),
        ("證據先行的草稿", "草稿裡的每個引用,都必須來自系統實際檢索到的文件;引用旁直接附上原文段落。"),
        ("期限自動試算", "從公文日期起算法定期限,假日自動順延,並給內部建議完成日。"),
        ("簽核才能送件", "律師逐句確認 AI / 人工段落;未完成簽核,匯出按鈕直接被系統擋下。"),
    ]
    x0, y0 = 1.0, 2.35
    for i, (h, b) in enumerate(cards):
        col = i % 2
        row = i // 2
        x = x0 + col * 5.95
        y = y0 + row * 1.78
        rect(s, x, y + 0.05, 0.06, 1.42, AMBER)
        txt(s, x + 0.28, y, 5.35, 0.5,
            [[("%d　" % (i + 1), 19, AMBER, True), (h, 19, NAVY, True)]])
        txt(s, x + 0.28, y + 0.55, 5.35, 1.1, one(b, 13.5, GRAY), leading=1.25)
    hline(s, 0.9, 6.05, 11.55, HAIR, 1.2)
    txt(s, 0.9, 6.2, 11.5, 0.6,
        [[("核心原則　", 15, AMBER, True),
          ("AI 是放大器,不是替代 — 每一份送出去的文件,都有具名律師逐句負責。",
           15, INK, False)]], leading=1.25)
    footer(s)


def s_arch():
    s = slide()
    kicker(s, "03", "系統怎麼運作")
    title(s, "系統架構：一條安全管線")
    p, h = add_pic_fitw(s, os.path.join(ASSETS, "architecture.png"), 0.62, 2.3, 12.1)
    txt(s, 0.9, 2.3 + h + 0.12, 11.6, 0.5,
        [[("兩條鐵則　", 14, AMBER, True),
          ("閘道永不直接呼叫模型;推論引擎不保存任何業務資料。", 13.5, GRAY, False)]])
    footer(s)


def s_trust():
    s = slide()
    kicker(s, "03", "系統怎麼運作")
    title(s, "四個「預設開啟、不可關閉」的信任設計")
    ghost_num(s, "03")
    cards = [
        ("可逆資料遮罩", "送往模型前,當事人、案號、聯絡方式先替換成代碼;對照表只存在事務所機器,模型拿到的永遠是代碼。"),
        ("引證驗證硬牆", "模型生成後,系統逐一比對引用是否真的存在於檢索結果;捏造的引用直接剝除並在畫面標示。"),
        ("不可竄改稽核", "每一筆請求寫入一列稽核紀錄,以雜湊鏈串接;任何竄改都會讓驗證亮紅燈,稽核員一鍵可驗。"),
        ("機密強制地端", "標記為機密的案件,系統強制改走事務所內的本地模型;就算設定錯誤,程式層也會直接拒絕外送。"),
    ]
    x0, y0 = 1.0, 2.35
    for i, (h, b) in enumerate(cards):
        col = i % 2
        row = i // 2
        x = x0 + col * 5.95
        y = y0 + row * 1.95
        rect(s, x, y + 0.05, 0.06, 1.6, NAVY)
        txt(s, x + 0.28, y, 5.35, 0.5, one(h, 18.5, NAVY, True))
        txt(s, x + 0.28, y + 0.52, 5.35, 1.25, one(b, 13.5, GRAY), leading=1.25)
    footer(s)


def s_shot(num_label, kick, ttl, shot, notes, base=None):
    s = slide()
    kicker(s, num_label, kick)
    title(s, ttl)
    path = os.path.join(base or SHOTS, shot)
    p, w = add_pic_fith(s, path, 0.9, 2.35, 4.05)
    nx = 0.9 + w + 0.55
    nw = SW - nx - 0.7
    y = 2.5
    for i, (head_, body_) in enumerate(notes):
        d = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(nx), Inches(y),
                               Inches(0.34), Inches(0.34))
        d.fill.solid(); d.fill.fore_color.rgb = AMBER; d.line.fill.background()
        d.shadow.inherit = False
        tf = d.text_frame; tf.margin_top = 0; tf.margin_bottom = 0
        r = tf.paragraphs[0].add_run(); r.text = str(i + 1)
        r.font.size = Pt(14); r.font.bold = True; r.font.color.rgb = WHITE
        set_font(r); tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        txt(s, nx + 0.5, y - 0.04, nw - 0.5, 0.4, one(head_, 15.5, NAVY, True))
        txt(s, nx + 0.5, y + 0.33, nw - 0.5, 0.8, one(body_, 12.5, GRAY),
            leading=1.16)
        y += 1.02
    footer(s)


def s_platform(num_label, ttl, who, what, bullet_lines, verify_line):
    s = slide()
    kicker(s, num_label, "平台整合實證")
    title(s, ttl)
    ghost_num(s, num_label)
    txt(s, 0.9, 2.15, 11.5, 0.5,
        [[(who + "　", 17, NAVY, True), (what, 15, GRAY, False)]], leading=1.25)
    bullets(s, 1.0, 3.05, 11.3, [(0, b, None) for b in bullet_lines],
            gap=0.24, size=15.5)
    hline(s, 0.9, 5.9, 11.55, HAIR, 1.2)
    txt(s, 0.9, 6.08, 11.5, 0.7,
        [[("實機驗證　", 15, AMBER, True), (verify_line, 14.5, INK, False)]],
        leading=1.25)
    footer(s)


def s_close():
    s = slide(NAVY)
    rect(s, 0, 0, SW, 0.16, AMBER)
    txt(s, 0.95, 0.9, 11, 0.8, one("現況與 Demo", 36, WHITE, True))
    stats = [
        ("1,232", "後端測試全綠"),
        ("73", "前端 E2E 全綠"),
        ("28 秒", "實機全鏈路分析"),
        ("0", "機密外送事件"),
    ]
    x0 = 0.95
    for i, (num, lab) in enumerate(stats):
        x = x0 + i * 2.95
        txt(s, x, 2.1, 2.7, 0.7, one(num, 38, AMBER, True))
        txt(s, x, 2.9, 2.7, 0.4, one(lab, 14, RGBColor(0xC6,0xD2,0xEE), False))
    hline(s, 0.97, 3.7, 11.4, RGBColor(0x3B,0x55,0x9E), 1.2)
    txt(s, 0.95, 3.95, 11.3, 0.45, one("現場 Demo 流程", 18, WHITE, True))
    demo = [
        "① 登入律師帳號,拖入真實的台灣審查意見書 PDF",
        "② 系統分類核駁、檢索證據、產出繁中申復書草稿與期限(經 digiRunner 與 Dify,本地模型)",
        "③ 切換稽核員帳號:驗證雜湊鏈,展示每一步的不可竄改紀錄",
    ]
    yy = 4.5
    for line in demo:
        txt(s, 1.1, yy, 11.1, 0.5, one(line, 15, RGBColor(0xC6,0xD2,0xEE), False))
        yy += 0.52
    txt(s, 0.95, 6.45, 11, 0.6,
        [[("Thank you.　", 20, WHITE, True),
          ("歡迎現場實際操作 — 整套系統就在這台機器上跑著。", 15,
           RGBColor(0x9D,0xAC,0xD4), False)]])


# ----------------- assembly: 15 slides -----------------
s_title()                                                              # 1
s_agenda()                                                             # 2
s_topic()                                                              # 3
s_motivation()                                                         # 4
s_solution()                                                           # 5
s_arch()                                                               # 6
s_trust()                                                              # 7
s_shot("04", "產品畫面", "畫面 ①｜登入與角色權限",
       "landing-desktop-1440-chromium-desktop.png", [
        ("官方入口風格", "乾淨版面、弱化技術術語;律師第一眼就知道在哪裡開始。"),
        ("四種角色", "律師 / 助理 / IT / 稽核 — 各自看到的功能與案件都不同。"),
        ("案件級權限", "登入身分決定可碰哪些案件,之後每一筆請求都重新檢查。"),
       ])
s_shot("04", "產品畫面", "畫面 ②｜分析工作台(三欄)",
       "analyze-empty-desktop-chromium-desktop.png", [
        ("左欄輸入", "案號 + 拖放 PDF / DOCX 或直接貼上 OA 全文。"),
        ("中右欄結果", "分析後中欄出申復書草稿,右欄列審查官引證與檢索命中的前案。"),
        ("安全狀態一眼可見", "頂部顯示「資料遮罩:開啟 / 資料保存於本地」;頁尾四燈顯示各服務健康狀態。"),
       ])
s_shot("04", "產品畫面", "畫面 ③｜草稿與引證驗證",
       "analyze-result-desktop-chromium-desktop.png", [
        ("生成 → 驗證兩段式", "草稿產生後系統自動驗證每個引用;查無實據的引用直接剝除並標示。"),
        ("引用可點開", "點任何引用即顯示來源文件與原文段落,律師不用自己翻。"),
        ("逐句簽核", "每句標示由 AI 或律師撰寫,逐句 Accept / Edit;全部確認才能匯出。"),
       ])
s_platform("05", "實機整合 ①｜digiRunner 前線閘道",
    "digiRunner(TPIsoftware 開源版)= 企業 API 閘道",
    "部署於 :18080,所有前端流量先經過它,再轉發到系統閘道。",
    [
        "路由全自動註冊:12 條 API 路由以管理 API 寫入,零手動設定,重啟自動重建",
        "身分標頭轉發:digiRunner 驗證後以信任標頭傳遞身分;偽造標頭一律 401",
        "為企業落地鋪路:SSO、流量治理、API 金鑰管理都在這一層接上",
    ],
    "瀏覽器 → digiRunner → 閘道 → 推論引擎完整走通;7 項自動化煙霧測試全數通過。")
s_platform("05", "實機整合 ②｜Dify AI 工作流",
    "Dify(社群版,自架)= AI workflow 編排平台",
    "部署於 :8088,申復書的解析與草擬透過 Dify workflow 呼叫本地模型 qwen2.5:7b。",
    [
        "一鍵自動建置:管理帳號、模型接入、workflow 匯入、API 金鑰全由腳本完成",
        "提示詞單一來源:workflow 由版本控制中的提示詞檔自動生成,不會兩邊不同步",
        "降級不裝死:Dify 斷線自動退回備援引擎,畫面出現醒目警示,絕不冒充真結果",
        "引證驗證留在系統內:防幻覺的最後一道牆不外包給任何平台",
    ],
    "真實 OA 經 Dify + 本地模型完整分析:28 秒產出正確分類與繁中草稿。")
s_shot("05", "平台整合實證", "實機證明 ①｜真模型分析結果",
       "real_05_result_real_qwen.png", [
        ("全鏈路 28 秒", "瀏覽器 → digiRunner → 閘道 → 推論引擎 → Dify → 本地模型,無一模擬。"),
        ("正確抓出瑕疵", "台灣 OA:請求項 9「該第一電動車」缺先行詞 — 真模型分類正確。"),
        ("硬牆當場攔截", "真模型也想捏造引用 — 系統即時剝除並在畫面標示。"),
        ("繁中申復書", "本地模型產出符合公文格式的申復書草稿,逐句簽核後才可匯出。"),
       ], base=DELIVERY_SHOTS)
s_shot("05", "平台整合實證", "實機證明 ②｜稽核鏈與服務狀態",
       "real_08_chain_verified.png", [
        ("記錄實際模型", "每筆分析的稽核列寫明用了哪個模型 — 可究責、可回溯。"),
        ("雜湊鏈全數驗證", "29 筆紀錄 0 不一致;一鍵驗證,竄改即現形。"),
        ("遮罩留痕", "命中的遮罩規則寫入稽核,證明遮罩真的有跑。"),
        ("四燈全綠", "頁尾即時顯示閘道 / 推論引擎 / digiRunner / Dify 健康狀態。"),
       ], base=DELIVERY_SHOTS)
s_close()

out = os.path.join(HERE, "PatentMind_簡報.pptx")
prs.save(out)
print("saved", len(prs.slides._sldIdLst), "slides OK")
