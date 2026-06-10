# -*- coding: utf-8 -*-
"""Three flow diagrams for the deck (same visual language as make_diagram.py):

  flow_user.png  - 操作流程: swimlanes 使用者操作 / 系統處理 / 產出
  flow_data.png  - 資料流:   來源 -> digiRunner -> 閘道 -> 推論/檢索 -> 去向
  flow_ai.png    - AI 任務:  提示組裝 -> 判斷 -> 呼叫工具 -> 草擬 -> 驗證 -> 回傳
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(HERE, "assets")

NAVY      = (30, 58, 138)
NAVY_DEEP = (18, 36, 92)
NAVY_LITE = (41, 82, 200)
AMBER     = (245, 176, 32)
AMBER_BG  = (255, 244, 214)
WHITE     = (255, 255, 255)
INK       = (28, 38, 64)
GRAY      = (110, 124, 156)
PALE      = (240, 243, 250)
PALE_LINE = (210, 218, 235)
GREEN     = (22, 130, 93)
GREEN_BG  = (225, 244, 236)

CJK   = "C:/Windows/Fonts/msjh.ttc"
CJK_B = "C:/Windows/Fonts/msjhbd.ttc"


def F(path, sz):
    return ImageFont.truetype(path, sz)


def text(d, xy, s, font, fill, anchor="la"):
    d.text(xy, s, font=font, fill=fill, anchor=anchor)


def rrect(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def shadow_card(base, box, r, fill, blur=10, alpha=55, dy=6):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    sd.rounded_rectangle([box[0], box[1] + dy, box[2], box[3] + dy],
                         radius=r, fill=(15, 25, 55, alpha))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh)
    ImageDraw.Draw(base).rounded_rectangle(box, radius=r, fill=fill)


def harrow(d, xa, xb, y, color=NAVY, w=7):
    d.line([(xa, y), (xb - 18, y)], fill=color, width=w)
    d.polygon([(xb, y), (xb - 24, y - 14), (xb - 24, y + 14)], fill=color)


def varrow(d, x, ya, yb, color=NAVY, w=7):
    d.line([(x, ya), (x, yb - 18)], fill=color, width=w)
    d.polygon([(x, yb), (x - 14, yb - 24), (x + 14, yb - 24)], fill=color)


# ====================================================================
# 1. flow_user.png — swimlane operation flow
# ====================================================================
def make_user_flow():
    W, H = 2360, 1130
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    f_lane = F(CJK_B, 34)
    f_box  = F(CJK_B, 30)
    f_sub  = F(CJK, 24)
    f_num  = F(CJK_B, 26)

    lanes = [("使用者操作", 175, 300, NAVY),
             ("系統處理", 495, 300, NAVY_DEEP),
             ("產出", 815, 255, AMBER)]
    left = 300
    for name, ly, lh, color in lanes:
        rrect(d, [60, ly, 250, ly + lh], 18, fill=color)
        # vertical-ish label centered
        text(d, (155, ly + lh / 2), name, f_lane, WHITE, anchor="mm")
        rrect(d, [left - 20, ly, W - 50, ly + lh], 18, fill=PALE)

    def box(cx, lane, w, label, sub, num=None, fill=WHITE, line=PALE_LINE,
            tcol=INK):
        ly, lh = lanes[lane][1], lanes[lane][2]
        cy = ly + lh / 2
        bh = 170 if sub else 120
        b = [cx - w / 2, cy - bh / 2, cx + w / 2, cy + bh / 2]
        shadow_card(img, b, 16, fill)
        rrect(d, b, 16, outline=line, width=3)
        if num:
            d.ellipse([b[0] + 18, b[1] + 18, b[0] + 62, b[1] + 62], fill=AMBER)
            text(d, (b[0] + 40, b[1] + 39), num, f_num, WHITE, anchor="mm")
        ty = cy - (26 if sub else 0)
        text(d, (cx + (16 if num else 0), ty), label, f_box, tcol, anchor="mm")
        if sub:
            text(d, (cx, cy + 38), sub, f_sub, GRAY, anchor="mm")
        return b

    # user lane steps
    b1 = box(490, 0, 300, "登入選案", "律師 / 助理", "1")
    b2 = box(870, 0, 320, "上傳 OA", "PDF 或貼文字", "2")
    b3 = box(1310, 0, 300, "按「分析」", None, "3")
    b4 = box(1840, 0, 380, "逐句簽核 / 編修", "確認 AI 段落", "4")
    # system lane steps
    s1 = box(870, 1, 360, "萃取 + 遮罩", "機密先變代碼")
    s2 = box(1310, 1, 360, "AI 分析管線", "分類→檢索→草擬\n→驗證→算期限")
    s3 = box(1840, 1, 380, "簽核閘", "未全數確認\n拒絕匯出")
    # output lane
    o1 = box(1310, 2, 380, "草稿 + 引證 + 期限", None)
    o2 = box(1840, 2, 330, "申復書匯出", None)
    o3 = box(2180, 2, 240, "稽核紀錄", "每一步都留痕", fill=GREEN_BG,
             line=GREEN, tcol=GREEN)

    # arrows
    mid0 = lanes[0][1] + lanes[0][2] / 2
    mid1 = lanes[1][1] + lanes[1][2] / 2
    mid2 = lanes[2][1] + lanes[2][2] / 2
    harrow(d, b1[2], b2[0], mid0)
    varrow(d, 870, b2[3], s1[1])
    harrow(d, s1[2], s2[0], mid1)
    varrow(d, 1310, b3[3], s2[1])           # user clicks analyze
    harrow(d, b2[2], b3[0], mid0)
    varrow(d, 1310, s2[3], o1[1])
    harrow(d, b3[2], b4[0], mid0)
    varrow(d, 1840, b4[3], s3[1])
    varrow(d, 1840, s3[3], o2[1])
    harrow(d, o2[2], o3[0], mid2)

    text(d, (60, 50), "從上傳到送件：使用者只做 4 件事", F(CJK_B, 50), NAVY)
    text(d, (62, 108), "其餘由系統完成；每一步（含失敗）都寫入稽核鏈", F(CJK, 28), GRAY)
    img.convert("RGB").save(os.path.join(ASSETS, "flow_user.png"), quality=95)
    print("flow_user.png")


# ====================================================================
# 2. flow_data.png — data flow
# ====================================================================
def make_data_flow():
    W, H = 2360, 1130
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    f_h   = F(CJK_B, 32)
    f_box = F(CJK_B, 29)
    f_sub = F(CJK, 23)

    def col_header(x0, x1, label, color=NAVY):
        rrect(d, [x0, 150, x1, 150 + 64], 16, fill=color)
        text(d, ((x0 + x1) / 2, 182), label, f_h, WHITE, anchor="mm")

    def card(x0, y0, x1, y1, label, sub, fill=WHITE, line=PALE_LINE, tcol=INK):
        shadow_card(img, [x0, y0, x1, y1], 14, fill)
        rrect(d, [x0, y0, x1, y1], 14, outline=line, width=3)
        cy = (y0 + y1) / 2
        text(d, ((x0 + x1) / 2, cy - (20 if sub else 0)), label, f_box, tcol, anchor="mm")
        if sub:
            text(d, ((x0 + x1) / 2, cy + 30), sub, f_sub, GRAY, anchor="mm")

    def cylinder(x0, y0, x1, y1, label, sub, line=NAVY):
        ry = 26
        d.ellipse([x0, y1 - ry * 2, x1, y1], fill=PALE, outline=line, width=3)
        d.rectangle([x0, y0 + ry, x1, y1 - ry], fill=PALE)
        d.line([(x0, y0 + ry), (x0, y1 - ry)], fill=line, width=3)
        d.line([(x1, y0 + ry), (x1, y1 - ry)], fill=line, width=3)
        d.ellipse([x0, y0, x1, y0 + ry * 2], fill=PALE, outline=line, width=3)
        cy = (y0 + y1) / 2 + 8
        text(d, ((x0 + x1) / 2, cy - 16), label, f_box, NAVY, anchor="mm")
        if sub:
            text(d, ((x0 + x1) / 2, cy + 26), sub, f_sub, GRAY, anchor="mm")

    # columns: 來源 | 入口 | 處理 | 去向
    col_header(70, 470, "資料從哪裡來")
    card(70, 270, 470, 420, "OA 文件", "律師上傳 PDF / 文字")
    card(70, 450, 470, 600, "專利與前案庫", "公報全文，建索引備查")
    card(70, 630, 470, 780, "官方行事曆", "期限順延的依據")

    col_header(560, 950, "從哪個門進來", NAVY_DEEP)
    card(560, 330, 950, 530, "digiRunner", "唯一入口：路由、身分\n轉發、流量治理", fill=WHITE, line=NAVY_DEEP, tcol=NAVY_DEEP)
    card(560, 580, 950, 720, "安全閘道", "權限檢查 → 遮罩\n→ 快取 → 稽核")

    col_header(1040, 1700, "經過哪些處理", NAVY)
    card(1040, 270, 1340, 430, "遮罩引擎", "機密→代碼\n（可逆，對照表僅地端）")
    card(1400, 270, 1700, 430, "向量檢索", "請求項樹切塊\n→ Qdrant 相似搜尋")
    card(1040, 480, 1340, 640, "Dify 工作流", "呼叫本地模型\nqwen2.5:7b")
    card(1400, 480, 1700, 640, "引證驗證", "捏造引用剝除", fill=AMBER_BG, line=AMBER)
    card(1040, 690, 1700, 800, "期限引擎", "公文日期 + 行事曆 → 法定期限")

    col_header(1790, 2290, "最後變成什麼", AMBER)
    card(1790, 270, 2290, 400, "申復書草稿", "含引證原文，待簽核")
    card(1790, 430, 2290, 540, "期限與提醒", None)
    cylinder(1790, 580, 2290, 760, "稽核資料庫", "只進不改 · 雜湊鏈")
    cylinder(1790, 800, 2290, 980, "遮罩對照表", "永遠只存事務所機器", line=GREEN)

    # arrows
    harrow(d, 470, 560, 460)            # sources -> digiRunner
    varrow(d, 755, 530, 580)            # digiRunner -> gateway
    harrow(d, 950, 1040, 600)           # gateway -> processing
    harrow(d, 1340, 1400, 350)          # mask -> retrieval
    varrow(d, 1190, 430, 480)           # mask -> dify
    harrow(d, 1340, 1400, 560)          # dify -> verify
    harrow(d, 1700, 1790, 350)          # -> outputs
    harrow(d, 1700, 1790, 560)
    harrow(d, 1700, 1790, 745)

    text(d, (60, 44), "每一步都知道資料在誰手上", F(CJK_B, 50), NAVY)
    text(d, (62, 102), "機密在進模型前就變成代碼；對照表與稽核紀錄永遠留在地端", F(CJK, 28), GRAY)
    img.convert("RGB").save(os.path.join(ASSETS, "flow_data.png"), quality=95)
    print("flow_data.png")


# ====================================================================
# 3. flow_ai.png — AI task / agent flow
# ====================================================================
def make_ai_flow():
    W, H = 2360, 1130
    img = Image.new("RGBA", (W, H), (255, 255, 255, 255))
    d = ImageDraw.Draw(img)
    f_box = F(CJK_B, 30)
    f_sub = F(CJK, 23)
    f_num = F(CJK_B, 28)

    def step(cx, cy, w, h, num, label, sub, fill=WHITE, line=PALE_LINE,
             tcol=INK):
        b = [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2]
        shadow_card(img, b, 16, fill)
        rrect(d, b, 16, outline=line, width=3)
        if num:
            d.ellipse([b[0] + 16, b[1] + 16, b[0] + 60, b[1] + 60], fill=NAVY)
            text(d, (b[0] + 38, b[1] + 37), num, f_num, WHITE, anchor="mm")
        text(d, (cx + (10 if num else 0), cy - (22 if sub else 0)), label,
             f_box, tcol, anchor="mm")
        if sub:
            lines = sub.split("\n")
            for j, l in enumerate(lines):
                text(d, (cx, cy + 30 + j * 32), l, f_sub, GRAY, anchor="mm")
        return b

    # top row: 1 -> 2 -> 3 ; bottom row: 4 -> 5 -> 6 (snake)
    y1, y2 = 330, 800
    b1 = step(420, y1, 600, 250, "1", "組裝提示", "系統指令 + 遮罩後 OA\n外部內容標記為「不可信」")
    b2 = step(1180, y1, 560, 250, "2", "模型判斷", "核駁類型？受影響請求項？\n中文／英文管轄？")
    b3 = step(1930, y1, 580, 250, "3", "呼叫工具", "向量檢索前案 · 請求項樹\n期限試算(行事曆)")
    b4 = step(1930, y2, 580, 250, "4", "草擬申復書", "逐核駁一份草稿\n引用只能來自檢索結果")
    b5 = step(1180, y2, 560, 250, "5", "引證驗證", "查無實據 → 剝除 + 標示\n（防幻覺硬牆，不可繞過）")
    b6 = step(420, y2, 600, 250, "6", "回傳結構化結果", "草稿 + 引證 + 期限 + 信心度\n含實際使用的模型名(稽核)")

    harrow(d, b1[2], b2[0], y1)
    harrow(d, b2[2], b3[0], y1)
    varrow(d, 1930, b3[3], b4[1])
    # leftward arrows (4 -> 5 -> 6) need manual draw
    d.line([(b4[0], y2), (b5[2] + 18, y2)], fill=NAVY, width=7)
    d.polygon([(b5[2], y2), (b5[2] + 24, y2 - 14), (b5[2] + 24, y2 + 14)], fill=NAVY)
    d.line([(b5[0], y2), (b6[2] + 18, y2)], fill=NAVY, width=7)
    d.polygon([(b6[2], y2), (b6[2] + 24, y2 - 14), (b6[2] + 24, y2 + 14)], fill=NAVY)

    # degrade branch under step 2/5
    db = [880, 1000, 2230, 1090]
    rrect(d, db, 14, fill=AMBER_BG, outline=AMBER, width=3)
    text(d, ((db[0] + db[2]) / 2, (db[1] + db[3]) / 2),
         "任一步失敗 → 自動降級備援引擎，結果標示「降級」並在畫面醒目警示，絕不冒充真實分析",
         f_sub, INK, anchor="mm")

    text(d, (60, 44), "先舉證、再下筆、寫完還要驗", F(CJK_B, 50), NAVY)
    text(d, (62, 102),
         "提示組裝 → 判斷 → 呼叫工具 → 草擬 → 驗證 → 回傳；機密案件全程只走地端模型",
         F(CJK, 28), GRAY)
    img.convert("RGB").save(os.path.join(ASSETS, "flow_ai.png"), quality=95)
    print("flow_ai.png")


if __name__ == "__main__":
    make_user_flow()
    make_data_flow()
    make_ai_flow()
