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
    print(f"Seeding patents → {url}")
    with httpx.Client(timeout=30.0) as client:
        for p in DEMO_PATENTS:
            r = client.post(url, json=p)
            if r.status_code != 200:
                print(f"  ✗ {p['patent_no']}: HTTP {r.status_code} {r.text}")
                sys.exit(1)
            data = r.json()
            print(f"  ✓ {p['patent_no']} ({p['jurisdiction']}, tenant={p['tenant_id']}): "
                  f"{data['chunks_indexed']} chunks")
    print(f"\nDone. {len(DEMO_PATENTS)} patents indexed.")


if __name__ == "__main__":
    main()
