"""Seed demo patents into the RAG index.

Runs by hitting the AI Engine /v1/index/patent endpoint. After this you can
do real queries through the gateway.

Usage:
    python -m backend.patent_db.seed
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from backend.shared.config import settings


DEMO_PATENTS = [
    {
        "tenant_id": "tenant_a",
        "patent_no": "US7654321",
        "title": "Microchannel cooling system for electric vehicle battery pack",
        "abstract": (
            "A cooling system for an electric vehicle battery pack comprises a "
            "plurality of microchannels formed in a base plate, each microchannel "
            "having a varying cross-section to induce turbulent flow and improve "
            "heat transfer to coolant."
        ),
        "claims": [
            "A cooling system, comprising: a base plate having a plurality of microchannels; "
            "each microchannel having a non-uniform cross-section along its length; and a "
            "coolant manifold coupled to said microchannels.",
            "The cooling system according to claim 1, wherein said non-uniform cross-section "
            "comprises alternating constrictions and expansions.",
            "The cooling system according to claim 1, further comprising temperature sensors "
            "embedded between adjacent microchannels.",
        ],
        "publication_date": "2018-04-15T00:00:00+00:00",
        "jurisdiction": "US",
        "is_local": False,
        "spec_text": (
            "FIELD OF THE INVENTION\n"
            "The present invention relates generally to thermal management for batteries, "
            "and more particularly to microchannel cooling for high-density EV battery packs.\n\n"
            "BACKGROUND\n"
            "Conventional cold plates with parallel rectangular channels suffer from laminar "
            "flow regimes that limit convective heat transfer. Prior art such as US6543210 "
            "discloses solid heat sinks that are inadequate for high-current discharge.\n\n"
            "SUMMARY\n"
            "The present invention provides a microchannel arrangement with periodic "
            "constrictions causing localised flow acceleration and turbulence, achieving up "
            "to 32% reduction in thermal resistance.\n\n"
            "DETAILED DESCRIPTION\n"
            "Referring to FIG. 1, the base plate 100 contains channels 102 with sinusoidal "
            "width modulation. Sensors 104 placed at peak constriction points permit closed-loop "
            "thermal control.\n"
        ),
    },
    {
        "tenant_id": "tenant_a",
        "patent_no": "US6543210",
        "title": "Solid copper heat sink for power electronics",
        "abstract": (
            "A solid copper heat sink with extruded fins for cooling power electronics. "
            "The heat sink relies on conductive heat transfer through a homogeneous block."
        ),
        "claims": [
            "A heat sink, comprising: a solid copper block with a plurality of parallel "
            "extruded fins extending vertically from a base."
        ],
        "publication_date": "2010-09-21T00:00:00+00:00",
        "jurisdiction": "US",
        "is_local": False,
        "spec_text": (
            "BACKGROUND\nSolid heat sinks are well-suited for low-density applications. "
            "Microchannel approaches are explicitly NOT recommended due to manufacturing complexity.\n"
        ),
    },
    {
        "tenant_id": "tenant_a",
        "patent_no": "TW202617461",
        "title": "電動車充電站之充電管理方法及系統",
        "abstract": (
            "一種電動車充電站之充電管理方法及系統，適用於包括複數電動車充電站之一充電場域與透過一第一網路連接至每一電動車充電站之一伺服器。"
            "首先，伺服器執行一能源管理方案以對於充電場域中之電動車充電站執行一負載管理作業，其中能源管理方案記錄一配電邏輯，"
            "用以控制充電場域中之每一者所相應之一充電作業。當負載管理作業執行時，伺服器取得電動車充電站中之一第一特定電動車充電站之一第一裝置資料，"
            "並依據相應第一特定電動車充電站之第一裝置資料決定第一特定電動車充電站相應負載管理作業的一第一參考值，其中第一參考值係可變動的。"
            "伺服器透過網路持續接收相應第一特定電動車充電站之一第一充電作業之一第一充電資料並依據第一充電資料與第一參考值判斷是否發生一特定事件。"
            "當特定事件發生時，伺服器停止對第一特定電動車充電站執行負載管理作業。"
        ),
        "claims": [
            # 請求項 1 — 獨立項（方法）
            "一種電動車充電站之充電管理方法，適用於包括複數電動車充電站之一充電場域與透過一第一網路連接至每一所述電動車充電站之一伺服器，該方法包括："
            "由該伺服器執行一能源管理方案以對於該充電場域中之該等電動車充電站執行一負載管理作業，其中該能源管理方案記錄一配電邏輯，"
            "用以控制該充電場域中之每一者所相應之一充電作業；"
            "由該伺服器取得該等電動車充電站中之一第一特定電動車充電站之一第一裝置資料，"
            "並依據相應該第一特定電動車充電站之該第一裝置資料決定該第一特定電動車充電站相應該負載管理作業的一第一參考值，其中該第一參考值係可變動的；"
            "由該伺服器透過該第一網路持續接收相應該第一特定電動車充電站之一第一充電作業之一第一充電資料，"
            "並依據該第一充電資料與該第一參考值判斷是否發生一特定事件；以及"
            "當該特定事件發生時，由該伺服器停止對該第一特定電動車充電站執行該負載管理作業。",
            # 請求項 2
            "如請求項1所述之充電管理方法，其中該第一裝置資料包括該第一特定電動車充電站之最大可供電功率與當前充電佔比之至少一者。",
            # 請求項 3
            "如請求項1所述之充電管理方法，其中該第一參考值包括相應該第一特定電動車充電站之一上限電流值，且該上限電流值會隨該配電邏輯而動態調整。",
            # 請求項 4
            "如請求項1所述之充電管理方法，其中該特定事件包括該第一充電資料中之實際電流超過該第一參考值達一預設容許區間時所觸發之過載事件。",
            # 請求項 5
            "如請求項1所述之充電管理方法，更包括：當該特定事件發生時，由該伺服器對該充電場域中之至少一其他電動車充電站重新分配剩餘可供電功率。",
            # 請求項 6
            "如請求項1所述之充電管理方法，其中該負載管理作業包括一週期性巡檢程序，由該伺服器於每一巡檢週期內取得該第一裝置資料並更新該第一參考值。",
            # 請求項 7
            "如請求項1所述之充電管理方法，其中該配電邏輯依據該充電場域之一即時總用電量與一場域契約容量之比值決定。",
            # 請求項 8
            "如請求項1所述之充電管理方法，更包括：當該特定事件發生時，由該伺服器產生一警示訊息並透過該第一網路傳送至一管理者終端。",
            # 請求項 9 — 這項就是 OA 指摘的：先行詞缺失（該第一電動車 沒在前面定義）
            "如請求項1所述之充電管理方法，其中當該特定事件發生時，該伺服器另向該第一電動車發送一充電終止通知，以暫停該第一電動車之充電。",
            # 請求項 10 — 獨立項（系統）
            "一種電動車充電站之充電管理系統，包括："
            "複數電動車充電站，位於一充電場域中；以及"
            "一伺服器，透過一第一網路連接至每一所述電動車充電站，並用以："
            "執行一能源管理方案以對於該等電動車充電站執行一負載管理作業，其中該能源管理方案記錄一配電邏輯；"
            "取得該等電動車充電站中之一第一特定電動車充電站之一第一裝置資料，並依據該第一裝置資料決定該第一特定電動車充電站相應該負載管理作業的一第一參考值，"
            "其中該第一參考值係可變動的；"
            "持續接收相應該第一特定電動車充電站之一第一充電作業之一第一充電資料，並依據該第一充電資料與該第一參考值判斷是否發生一特定事件；以及"
            "於該特定事件發生時，停止對該第一特定電動車充電站執行該負載管理作業。",
        ],
        "publication_date": "2026-05-01T00:00:00+00:00",
        "jurisdiction": "TW",
        "is_local": False,
        "spec_text": (
            "發明所屬之技術領域\n"
            "本發明係關於一種電動車充電站之充電管理方法及系統，尤指於一充電場域中以伺服器執行能源管理方案，依據充電站之裝置資料動態決定參考值並監控特定事件之充電管理技術。\n\n"
            "先前技術\n"
            "習知充電場域多採固定上限分配電力，當充電負載集中時容易超過場域契約容量；另有以平均分配方式控制，但無法因應充電站個別狀態差異。\n\n"
            "發明內容\n"
            "本發明提出一種以伺服器執行能源管理方案之充電管理方法，依據充電站之第一裝置資料決定可變動之第一參考值，並依據持續接收之第一充電資料判斷是否發生特定事件，於特定事件發生時停止對該充電站執行負載管理作業，藉以兼顧場域用電安全與充電效率。\n\n"
            "實施方式\n"
            "請參閱第一圖，充電場域100包括複數電動車充電站102_1~102_N，伺服器110透過第一網路120連接每一充電站。伺服器110之能源管理方案記錄一配電邏輯，用以決定每一充電站之可供電功率。當伺服器110取得第一特定電動車充電站102_1之第一裝置資料時，依據該第一裝置資料決定相應之第一參考值（例如電流上限），並透過第一網路120持續接收第一特定電動車充電站102_1之第一充電作業之第一充電資料（例如實際電流、充電功率）。當第一充電資料超過第一參考值達預設容許區間時，伺服器110判斷發生特定事件，並停止對該第一特定電動車充電站執行負載管理作業，避免發生過載。\n"
        ),
    },
    {
        "tenant_id": "tenant_a",
        "patent_no": "TW202131234",
        "title": "本國廠商 EV 電池冷卻管路設計",
        "abstract": (
            "一種電動車電池模組冷卻結構，包括具備非均勻截面之微流道板，提供電池芯之直接散熱。"
        ),
        "claims": [
            "一種電池冷卻結構，包含：基板，其上設置複數個微流道；每一微流道沿長度方向具有不均勻截面。",
        ],
        "publication_date": "2021-09-01T00:00:00+00:00",
        "jurisdiction": "TW",
        "is_local": True,    # 客戶內部專利
        "spec_text": "本發明涉及電動車冷卻系統，尤指採用微流道板之冷卻設計。",
    },
    {
        "tenant_id": "tenant_b",
        "patent_no": "EP3210987",
        "title": "Wireless charging coil alignment system",
        "abstract": "A wireless charging system with active coil alignment for misalignment tolerance.",
        "claims": [
            "A wireless charging system, comprising: a transmitting coil array; "
            "a position sensor; and a controller that energises selected coils based on receiver position."
        ],
        "publication_date": "2019-06-12T00:00:00+00:00",
        "jurisdiction": "EP",
        "is_local": False,
        "spec_text": "FIELD: wireless power transfer.\nBACKGROUND: misalignment reduces efficiency.",
    },
]


def main():
    url = f"{settings.AI_ENGINE_URL}/v1/index/patent"
    # AI Engine requires a matching X-Internal-Token whenever INTERNAL_TOKEN
    # is configured (main.py middleware). Send it so seeding works against a
    # secured engine; empty token (local-dev/pytest mock) sends no header,
    # matching the engine's "empty + mock = permit" rule.
    headers = (
        {"X-Internal-Token": settings.INTERNAL_TOKEN}
        if settings.INTERNAL_TOKEN
        else {}
    )
    print(f"Seeding patents → {url}")
    with httpx.Client(timeout=30.0) as client:
        for p in DEMO_PATENTS:
            r = client.post(url, json=p, headers=headers)
            if r.status_code != 200:
                print(f"  ✗ {p['patent_no']}: HTTP {r.status_code} {r.text}")
                sys.exit(1)
            data = r.json()
            print(f"  ✓ {p['patent_no']} ({p['jurisdiction']}, tenant={p['tenant_id']}): "
                  f"{data['chunks_indexed']} chunks")
    print(f"\nDone. {len(DEMO_PATENTS)} patents indexed.")


if __name__ == "__main__":
    main()
