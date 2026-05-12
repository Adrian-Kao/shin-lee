"""Render 30 synthetic cases into per-case folders.

Usage:
    python scripts/render_cases.py

Reads CASES from data/cases/synthetic_cases.py and writes:
    data/cases/<CASE_ID>/patent.txt
    data/cases/<CASE_ID>/oa.txt
    data/cases/<CASE_ID>/reexam.txt     (only when case has reexam)
    data/cases/manifest.json            (compact index of all cases)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.cases.synthetic_cases import (  # noqa: E402
    CASES,
    case_summary,
    render_oa_text,
    render_patent_text,
    render_reexam_text,
)


def main() -> None:
    out_root = ROOT / "data" / "cases"
    out_root.mkdir(parents=True, exist_ok=True)

    summaries: list[dict] = []
    n_patent = n_oa = n_reexam = 0

    for case in CASES:
        case_id = case["case_id"]
        case_dir = out_root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)

        (case_dir / "patent.txt").write_text(render_patent_text(case), encoding="utf-8")
        n_patent += 1

        (case_dir / "oa.txt").write_text(render_oa_text(case), encoding="utf-8")
        n_oa += 1

        if case.get("reexam"):
            (case_dir / "reexam.txt").write_text(render_reexam_text(case), encoding="utf-8")
            n_reexam += 1
        else:
            stale = case_dir / "reexam.txt"
            if stale.exists():
                stale.unlink()

        summaries.append(case_summary(case))

    manifest = {
        "version": "1.0",
        "case_count": len(CASES),
        "patents_written": n_patent,
        "oas_written": n_oa,
        "reexams_written": n_reexam,
        "cases": summaries,
    }
    (out_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"Rendered {len(CASES)} cases under {out_root}:")
    print(f"  patents : {n_patent}")
    print(f"  OAs     : {n_oa}")
    print(f"  reexams : {n_reexam}")
    print(f"  manifest: {out_root / 'manifest.json'}")


if __name__ == "__main__":
    main()
