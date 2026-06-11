"""Cut the raw Playwright footage into a ~30s captioned demo MP4.

Reads frontend/demo_video_out/marks.json (phase timestamps from
demo_video.mjs), slices the webm into eight captioned segments (plain
black-and-white subtitle style), time-lapses the real AI inference, and
concatenates to docs/demo/PatentMind_demo_30s.mp4 (~32s, no brand cards).

Uses Playwright's bundled ffmpeg — no system install needed.
Run from repo root: PYTHONUTF8=1 python scripts/make_demo_video.py
"""
import glob
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW_DIR = os.path.join(ROOT, "frontend", "demo_video_out")
OUT_DIR = os.path.join(ROOT, "docs", "demo")
TMP = os.path.join(RAW_DIR, "_segs")
FONT = "C\\:/Windows/Fonts/msjhbd.ttc"

# Needs a FULL ffmpeg (libx264 + drawtext); the Playwright bundled one is a
# minimal vp8-only build. winget install Gyan.FFmpeg provides this path.
candidates = sorted(glob.glob(
    "C:/Users/*/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_*/"
    "ffmpeg-*/bin/ffmpeg.exe"))
if not candidates:
    sys.exit("full ffmpeg not found — winget install Gyan.FFmpeg")
FFMPEG = candidates[-1]

ENC = ["-c:v", "libx264", "-preset", "medium", "-crf", "20",
       "-pix_fmt", "yuv420p", "-r", "30", "-an"]


def run(args):
    r = subprocess.run([FFMPEG, "-y", *args], capture_output=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print(r.stderr[-2500:])
        sys.exit(f"ffmpeg failed: {' '.join(args[:8])}...")


def caption_filter(text):
    # ':' and ',' are filtergraph separators — escape them inside text=
    text = text.replace(":", "\\:").replace(",", "\\,")
    # plain black-and-white subtitle style per review feedback
    return (f"drawtext=fontfile='{FONT}':text='{text}':fontsize=48:"
            f"fontcolor=white:x=(w-text_w)/2:y=h-132:box=1:"
            f"boxcolor=black@0.72:boxborderw=22")


def probe_duration(path):
    r = subprocess.run([FFMPEG, "-i", path], capture_output=True,
                       encoding="utf-8", errors="replace")
    for line in r.stderr.splitlines():
        if "Duration" in line:
            hh, mm, ss = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(hh) * 3600 + int(mm) * 60 + float(ss)
    sys.exit("could not probe raw duration")


def main():
    meta = json.load(open(os.path.join(RAW_DIR, "marks.json"), encoding="utf-8"))
    raw = os.path.join(RAW_DIR, meta["video"])
    # Playwright's screencast clock drifts vs wall clock — rescale marks so
    # they land on the actual video timeline.
    dur = probe_duration(raw)
    k = dur / meta["marks"]["end"]
    m = {key: v * k for key, v in meta["marks"].items()}
    print(f"raw video {dur:.2f}s, wall {meta['marks']['end']:.2f}s, scale {k:.4f}")
    os.makedirs(TMP, exist_ok=True)
    os.makedirs(OUT_DIR, exist_ok=True)

    # (start, end, speed, caption) — no brand cards, pure product footage
    segs = [
        (max(0.0, m["login_page"] - 0.8), m["logged_in"] + 0.5, 1.0,
         "律師登入，每位使用者只能存取自己的案件"),
        (m["logged_in"] + 0.5, m["upload_clicked"] + 0.7, 1.0,
         "填入案號，直接丟入審查意見書 PDF"),
        (m["upload_clicked"] + 0.7, m["analyze_clicked"] - 0.5, 1.0,
         "系統自動萃取全文，機密資訊先遮罩成代碼"),
        (m["analyze_clicked"] - 0.5, m["result_ready"] - 0.4, 6.5,
         "AI 分析中（快轉）— 地端模型 qwen2.5:7b，資料不出機器"),
        (m["result_ready"] - 0.4, m["rejections_viewed"], 1.0,
         "自動分類核駁理由，標出受影響的請求項"),
        (m["rejections_viewed"], m["draft_viewed"], 1.0,
         "產出繁中申復書草稿，引用逐一驗證、杜絕幻覺"),
        (m["draft_viewed"], m["deadline_viewed"], 1.0,
         "法定答辯期限自動試算，假日自動順延"),
        (m["deadline_viewed"], m["end"], 1.0,
         "全程寫入稽核鏈 — 一鍵驗證，不可竄改"),
    ]

    files = []

    for i, (a, b, speed, cap) in enumerate(segs, start=1):
        f = os.path.join(TMP, f"{i:02d}_seg.mp4")
        vf = f"scale=1920:1080,setpts=PTS/{speed},{caption_filter(cap)}"
        # -ss BEFORE -i: accurate input seek with PTS reset to 0, so the
        # setpts speed-up doesn't shift the trim window.
        run(["-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", raw,
             "-vf", vf, *ENC, f])
        files.append(f)
        print(f"seg{i}: {a:.1f}–{b:.1f}s ×{speed} → {(b - a) / speed:.1f}s  {cap}")

    lst = os.path.join(TMP, "concat.txt")
    with open(lst, "w", encoding="utf-8") as fh:
        for f in files:
            fh.write(f"file '{f.replace(os.sep, '/')}'\n")
    out = os.path.join(OUT_DIR, "PatentMind_demo_30s.mp4")
    run(["-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", out])

    probe = subprocess.run([FFMPEG, "-i", out], capture_output=True,
                           encoding="utf-8", errors="replace")
    for line in probe.stderr.splitlines():
        if "Duration" in line:
            print(line.strip())
    print("DONE →", out)


if __name__ == "__main__":
    main()
