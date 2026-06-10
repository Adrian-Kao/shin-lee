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
    add_pic_fith(s, os.path.join(ASSETS, "logo_word_white.png"), 0.95, 1.15, 1.15)
    txt(s, 0.95, 3.0, 11.4, 1.6,
        one("專利答辯安全 LLM 閘道", 46, WHITE, True))
    txt(s, 0.97, 4.15, 11.4, 1.2,
        [[("在 ", 19, RGBColor(0xC6,0xD2,0xEE), False),
          ("絕不讓客戶機密外洩到公有 LLM", 19, AMBER, True),
          (" 的前提下,半自動產出專利 OA 答辯稿", 19, RGBColor(0xC6,0xD2,0xEE), False)]])
    hline(s, 0.97, 5.05, 5.2, RGBColor(0x3B,0x55,0x9E), 1.2)
    txt(s, 0.97, 5.25, 11, 0.5,
        one("產品 SPA + 厚 Gateway + AI Engine　·　20 項架構決策 · 611 測試綠燈", 14,
            RGBColor(0xAEB if False else 0x9D, 0xAC, 0xD4)))
    txt(s, 0.97, 6.55, 11, 0.4,
        one("NCCU GDGoC × Computex 2026　|　Proof of Concept", 13,
            RGBColor(0x8D,0x9C,0xC4)))


def s_agenda():
    s = slide()
    kicker(s, "00", "Agenda")
    title(s, "簡報大綱")
    items = [
        ("1", "題目說明", "我們在做什麼"),
        ("2", "動機", "為什麼值得做"),
        ("3", "使用技術", "技術選型一覽"),
        ("4", "產品功能說明", "架構圖 + 前端畫面"),
        ("5", "Dify 與 digiRunner", "兩個平台怎麼對應"),
        ("6", "未來展望 · 收穫與心得", "上線整備與反思"),
        ("7", "Demo", "現場操作流程"),
    ]
    x0, y0 = 1.0, 2.25
    colw = 5.9
    for i, (n, t, sub) in enumerate(items):
        col = i // 4
        row = i % 4
        x = x0 + col * (colw + 0.5)
        y = y0 + row * 1.08
        txt(s, x, y - 0.02, 0.8, 0.8, one(n, 30, AMBER, True))
        txt(s, x + 0.7, y + 0.02, colw - 0.7, 0.5, one(t, 19, INK, True))
        txt(s, x + 0.7, y + 0.46, colw - 0.7, 0.4, one(sub, 12.5, GRAY))
    footer(s)


def s_divider(num, title_zh, title_en):
    s = slide(NAVY)
    rect(s, 0, 0, 0.16, SH, AMBER)
    txt(s, 0.7, 1.2, 6, 4.2, one(num, 300, NAVY_GHOST, True),
        anchor=MSO_ANCHOR.MIDDLE)
    txt(s, 6.0, 2.85, 6.7, 1.2, one(title_zh, 44, WHITE, True),
        anchor=MSO_ANCHOR.BOTTOM)
    txt(s, 6.05, 4.15, 6.7, 0.6, one(title_en, 17, AMBER, True))
    hline(s, 6.06, 4.0, 3.0, RGBColor(0x3B,0x55,0x9E), 1.4)


def s_topic():
    s = slide()
    kicker(s, "01", "題目說明")
    title(s, "為受規範領域打造的可信任 AI 閘道")
    ghost_num(s, "01")
    txt(s, 0.9, 2.15, 11.5, 0.9,
        [[("一句話：", 17, NAVY, True),
          ("半自動產出專利審查意見(Office Action)答辯稿,且全程不讓機密進入公有 LLM。",
           17, INK, False)]], leading=1.25)
    txt(s, 0.9, 3.0, 11.5, 0.7,
        [[("真正的重點不是專利流程,而是底層的「安全 / 可信任 AI 閘道」模式 — ",
           15, GRAY, False),
          ("可套用到任何處理機密、受合規規範資料的 AI 應用。", 15, NAVY, True)]],
        leading=1.25)
    bullets(s, 1.0, 4.0, 11.3, [
        (0, "服務三種角色:律師(撰稿簽核)、事務所(合規與責任)、客戶(資料機密)", None),
        (0, "範圍:6 國管轄試作(US / TW / CN / KR / EP / JP),端到端可跑的 PoC", None),
        (0, "成果:20 項架構決策落地為「不可關閉的不變式」,611 項測試綠燈", None),
        (0, "與業界平台對齊:API Gateway → digiRunner、AI workflow → Dify", None),
    ], gap=0.16, size=16)
    footer(s)


def s_motivation():
    s = slide()
    kicker(s, "02", "動機")
    title(s, "律師手動答辯 OA 的四大風險")
    ghost_num(s, "02")
    cards = [
        ("慢", "讀 OA、找前案、寫答辯 = 8–12 小時 / 案,人力成本高。"),
        ("幻覺風險", "引用錯誤法條或捏造判例 = 專業責任事故。"),
        ("期限風險", "法定期日算錯 = 專利權喪失,且無法復原。"),
        ("機密性", "客戶案件資料絕不能貼進 ChatGPT。"),
    ]
    x0, y0 = 1.0, 2.3
    for i, (h, b) in enumerate(cards):
        col = i % 2
        row = i // 2
        x = x0 + col * 5.85
        y = y0 + row * 1.5
        rect(s, x, y + 0.05, 0.06, 1.05, AMBER)
        txt(s, x + 0.28, y, 5.2, 0.5, one(h, 21, NAVY, True))
        txt(s, x + 0.28, y + 0.52, 5.2, 0.9, one(b, 14.5, GRAY), leading=1.2)
    hline(s, 0.9, 5.55, 11.55, HAIR, 1.2)
    txt(s, 0.9, 5.7, 11.5, 0.9,
        [[("為什麼不能直接用 ChatGPT:", 16, NAVY, True),
          ("資料外洩 × 幻覺 × 無稽核 × 無究責。PatentMind 四者同時解,而律師仍對每一句話負責。",
           16, INK, False)]], leading=1.3)
    footer(s)


def s_tech():
    s = slide()
    kicker(s, "03", "使用技術")
    title(s, "技術選型一覽")
    ghost_num(s, "03")
    groups = [
        ("後端", ["FastAPI 雙服務:Gateway :8010 / AI Engine :8011",
                 "Pydantic 型別 · SQLite append-only 稽核(hash chain)"]),
        ("前端", ["React 18 + Vite · TanStack Query · Tailwind",
                 "react-i18next(zh-TW / EN)· lucide icons · RWD"]),
        ("AI / RAG", ["多模型路由 · grounded citation + verifier 兩段式",
                      "Hierarchical + Claim-tree chunking · 向量檢索(Qdrant 形狀)"]),
        ("資安", ["JWT(RS256)+ case ACL · PII / 客戶詞庫遮罩(可逆)",
                 "Prompt injection 四層防禦 · 成本斷路器 + 配額"]),
        ("測試 / 維運", ["pytest 611 綠 · Playwright e2e + 視覺回歸",
                       "env 一鍵抽換 mock↔prod(LLM_MODE / VECTOR_BACKEND / CACHE_BACKEND)"]),
        ("平台對齊", ["digiRunner — API Gateway 層",
                    "Dify — AI workflow 編排層"]),
    ]
    x0, y0 = 1.0, 2.25
    colw = 5.85
    for i, (h, lines) in enumerate(groups):
        col = i % 2
        row = i // 2
        x = x0 + col * colw
        y = y0 + row * 1.55
        txt(s, x, y, 0.2, 0.9, one("▍", 18, AMBER, True))
        txt(s, x + 0.28, y, colw - 0.5, 0.4, one(h, 17, NAVY, True))
        txt(s, x + 0.28, y + 0.42, colw - 0.55, 1.0,
            [para(lines[0], 13, GRAY), para(lines[1], 13, GRAY)], leading=1.15,
            space_after=2)
    footer(s)


def s_arch():
    s = slide()
    kicker(s, "04", "產品功能說明")
    title(s, "系統架構：一條「安全管線」")
    p, h = add_pic_fitw(s, os.path.join(ASSETS, "architecture.png"), 0.62, 2.15, 12.1)
    txt(s, 0.9, 2.05 + h + 0.12, 11.6, 0.5,
        [[("兩條鐵則守住安全邊界:", 13.5, NAVY, True),
          ("① Gateway 永不直接呼叫 LLM　② AI Engine 不存任何業務狀態。",
           13.5, GRAY, False)]])
    footer(s)


def s_shot(num_label, ttl, shot, notes, fit="h", note_side="right"):
    s = slide()
    kicker(s, "04", "產品功能說明 · 前端畫面")
    title(s, ttl)
    path = os.path.join(SHOTS, shot)
    if fit == "h":   # desktop: image left, notes right
        p, w = add_pic_fith(s, path, 0.9, 2.35, 4.05)
        nx = 0.9 + w + 0.55
        nw = SW - nx - 0.7
    else:            # mobile: narrow image left, notes right
        p, w = add_pic_fith(s, path, 1.1, 2.3, 4.3)
        nx = 1.1 + w + 0.7
        nw = SW - nx - 0.7
    y = 2.5
    for i, (head, body) in enumerate(notes):
        # amber number disc
        d = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(nx), Inches(y),
                               Inches(0.34), Inches(0.34))
        d.fill.solid(); d.fill.fore_color.rgb = AMBER; d.line.fill.background()
        d.shadow.inherit = False
        tf = d.text_frame; tf.margin_top = 0; tf.margin_bottom = 0
        r = tf.paragraphs[0].add_run(); r.text = str(i + 1)
        r.font.size = Pt(14); r.font.bold = True; r.font.color.rgb = WHITE
        set_font(r); tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        txt(s, nx + 0.5, y - 0.04, nw - 0.5, 0.4, one(head, 15.5, NAVY, True))
        h = txt(s, nx + 0.5, y + 0.33, nw - 0.5, 0.8, one(body, 12.5, GRAY),
                leading=1.16)
        y += 1.02
    footer(s)


def s_platforms():
    s = slide()
    kicker(s, "05", "Dify 與 digiRunner")
    title(s, "兩個平台,各司其職")
    ghost_num(s, "05")
    # digiRunner column
    x = 1.0
    rect(s, x, 2.25, 0.07, 2.0, NAVY)
    txt(s, x + 0.3, 2.2, 5.3, 0.5,
        [[("digiRunner", 20, NAVY, True), ("　= API Gateway 層", 14, GRAY, False)]])
    txt(s, x + 0.3, 2.72, 5.3, 0.4,
        one("POC 用 FastAPI 模擬「厚 Gateway」:8010", 13, INK))
    bullets(s, x + 0.3, 3.15, 5.4, [
        (0, "Auth / case ACL、限流配額、遮罩、快取、編排、稽核", None),
        (0, "把資安與業務治理集中在「一處」管", None),
        (0, "對應決策 Q1 · Q12 · Q18 · Q10 · Q9 · Q13", None),
    ], gap=0.12, size=13.5)
    # Dify column
    x2 = 7.1
    rect(s, x2, 2.25, 0.07, 2.0, AMBER)
    txt(s, x2 + 0.3, 2.2, 5.3, 0.5,
        [[("Dify", 20, NAVY, True), ("　= AI workflow 層", 14, GRAY, False)]])
    txt(s, x2 + 0.3, 2.72, 5.3, 0.4,
        one("POC 用 FastAPI 模擬「純推論」:8011", 13, INK))
    bullets(s, x2 + 0.3, 3.15, 5.3, [
        (0, "每個 AI 工具包成 single-step endpoint", None),
        (0, "parse_oa / retrieve / draft / verify / deadline", None),
        (0, "未來換成 Dify HTTP node,介面已對齊", None),
    ], gap=0.12, size=13.5)
    hline(s, 0.9, 5.15, 11.55, HAIR, 1.2)
    txt(s, 0.9, 5.32, 11.6, 1.4, [
        [("分層化解衝突(Q1 厚 Gateway × Q2 Dify 編排):", 15, NAVY, True),
         ("Gateway 管高階業務流程,Dify 只做 AI sub-workflow。", 15, INK, False)],
        [("鐵則　", 14, AMBER, True),
         ("Gateway 永不直接打 LLM;Dify 不存業務狀態。", 14, INK, False)],
        [("分工　", 14, AMBER, True),
         ("設計師用 Dify 拉流程,工程師自寫關鍵 tool(OA parser / citation verifier / deadline)。",
          14, INK, False)],
    ], leading=1.25, space_after=8)
    footer(s)


def s_future():
    s = slide()
    kicker(s, "06", "未來展望 · 收穫與心得")
    title(s, "上線整備與反思")
    ghost_num(s, "06")
    txt(s, 1.0, 2.2, 5.6, 0.4, one("未來展望(P0 上線整備)", 17, NAVY, True))
    bullets(s, 1.0, 2.65, 5.6, [
        (0, "接真實 Anthropic / OpenAI;機密案件走地端 Llama", None),
        (0, "SQLite → Postgres + S3 Object Lock(WORM)封存", None),
        (0, "記憶體快取 → Redis;numpy → Qdrant 向量庫", None),
        (0, "PDF / DOCX 上傳 + Vision 讀圖;OIDC / SAML SSO", None),
        (0, "Prometheus + Grafana 可觀測性與 AI 品質評測", None),
    ], gap=0.13, size=13.5)
    txt(s, 7.0, 2.2, 5.4, 0.4, one("收穫與心得", 17, NAVY, True))
    bullets(s, 7.0, 2.65, 5.4, [
        (0, "把 20 項架構決策變成「測試守得住的不變式」,而非口頭規範", None),
        (0, "安全與信任不是功能,是預設不可關閉的閘道 — 這就是護城河", None),
        (0, "受規範領域導入 AI,瓶頸在「可稽核 + 可究責」,不在模型本身", None),
        (0, "Mock-first 讓 demo 可重現,又能 env 一鍵換成 production 元件", None),
    ], gap=0.13, size=13.5)
    footer(s)


def s_demo():
    s = slide()
    kicker(s, "07", "Demo")
    title(s, "現場操作流程")
    ghost_num(s, "07")
    steps = [
        ("以 Alice(律師)登入", "分析 CASE-2025-001", "Q12"),
        ("預覽 redaction", "email / 電話 / 案號 → placeholder", "Q10"),
        ("跑分析 → 點 [GROUNDED_REF_1]", "看來源專利 + 段落 + 原文", "Q14"),
        ("逐句 Accept / Edit", "全部簽核才能匯出答辯稿", "Q16"),
        ("以 Dave(稽核)登入", "看 audit log + 驗證 hash chain(綠)", "Q13"),
        ("改用 -CONF 案號", "audit 模型自動切地端", "Q15"),
        ("改用 Carol 登入", "403 — 她不在這個 case", "Q12"),
    ]
    x0, y0 = 1.0, 2.25
    for i, (a, b, q) in enumerate(steps):
        col = i // 4
        row = i % 4
        x = x0 + col * 5.95
        y = y0 + row * 1.02
        txt(s, x, y, 0.55, 0.5, one("%02d" % (i + 1), 20, AMBER, True))
        txt(s, x + 0.62, y - 0.02, 5.0, 0.4,
            [[(a, 14.5, INK, True), ("　" + q, 11, AMBER, True)]])
        txt(s, x + 0.62, y + 0.38, 5.0, 0.4, one(b, 12, GRAY))
    footer(s)


def s_end():
    s = slide(NAVY)
    rect(s, 0, 0, SW, 0.16, AMBER)
    add_pic_fith(s, os.path.join(ASSETS, "logo_word_white.png"), 0.95, 2.5, 1.2)
    txt(s, 0.97, 4.2, 11, 0.7, one("謝謝聆聽　·　歡迎 Demo 與提問", 26, WHITE, True))
    txt(s, 0.99, 5.1, 11, 0.5,
        one("可信任 AI 閘道 — 讓每一個 AI 主張都可驗證、每一個動作都可稽核。",
            15, RGBColor(0xC6,0xD2,0xEE)))


# ----------------- assemble -----------------
s_title()
s_agenda()

s_divider("1", "題目說明", "What it is")
s_topic()

s_divider("2", "動機", "Why it matters")
s_motivation()

s_divider("3", "使用技術", "Tech stack")
s_tech()

s_divider("4", "產品功能說明", "Product & screens")
s_arch()
s_shot("04", "前端畫面 ①｜登入與角色權限(RBAC)",
       "landing-desktop-1440-chromium-desktop.png", [
        ("官方入口風格", "仿專利局入口的乾淨版面,navy 主色 + 金色頂線,弱化技術術語。"),
        ("四種角色登入", "Alice 律師 / Bob 助理 / Carol IT / Dave 稽核 — 直接示範權限分流。"),
        ("租戶標示", "每位使用者標 tenant_a / tenant_b,呼應多租戶隔離(Q5)。"),
        ("case ACL 前置", "登入身分決定可存取哪些 case,後續每筆請求都會檢查(Q12)。"),
       ])
s_shot("04", "前端畫面 ②｜分析主工作台(三欄)",
       "analyze-empty-desktop-chromium-desktop.png", [
        ("輸入 OA(左欄)", "Case ID + 本案號 + 拖放 PDF/DOCX 或貼上全文,並即時顯示配額(Q18)。"),
        ("草稿 / 引證(中右欄)", "分析後中欄出答辯草稿、右欄列 examiner 引證 + RAG 命中前案。"),
        ("資料狀態列", "頂部「資料遮罩:開啟 / 保存於本地 / 一般案件」一眼看出安全狀態(Q3·Q10)。"),
        ("紀錄已驗證", "右上徽章顯示稽核鏈已驗證,強調可信任(Q13)。"),
       ])
s_shot("04", "前端畫面 ③｜分析結果與 grounded 引證",
       "analyze-result-desktop-chromium-desktop.png", [
        ("生成 → 驗證兩段式", "草稿產生後跑 citation verifier,合法引證才保留(Q14)。"),
        ("可點擊引證 pill", "[GROUNDED_REF_N] hover 顯示來源專利 + 段落 + 原文,杜絕幻覺。"),
        ("被移除的引證", "不在 grounded set 的引用會標為 [CITATION_REMOVED] 並顯示。"),
        ("逐句 provenance", "每句標示來源(AI / 律師),逐句 Accept / Edit(Q16)。"),
       ])
s_shot("04", "前端畫面 ④｜行動版 RWD",
       "landing-mobile-375-chromium-mobile.png", [
        ("單欄自適應", "375px 寬下版面自動收合為單欄,行動裝置也能操作。"),
        ("一致的設計語言", "與桌面版共用 navy 主題與元件,維持品牌一致性。"),
        ("底部分頁列", "行動版以底部 tab bar 切換 分析 / 案件 / Audit。"),
       ], fit="h")

s_divider("5", "Dify 與 digiRunner", "Platform mapping")
s_platforms()

s_divider("6", "未來展望 · 收穫與心得", "Roadmap & takeaways")
s_future()

s_divider("7", "Demo", "Live walkthrough")
s_demo()

s_end()

out = os.path.join(HERE, "PatentMind_簡報.pptx")
prs.save(out)
print("saved", len(prs.slides._sldIdLst), "slides OK")
