"""Cut the raw Playwright footage into a ~30s captioned demo MP4.

Reads frontend/demo_video_out/marks.json (phase timestamps from
demo_video.mjs), slices the webm into segments, speeds up the AI-inference
wait, burns zh-TW captions, prepends/appends 1080p brand cards from the
deck, and concatenates to docs/demo/PatentMind_demo_30s.mp4.

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
CARDS = os.path.join(ROOT, "presentation", "render_hd")
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
    return (f"drawtext=fontfile='{FONT}':text='{text}':fontsize=46:"
            f"fontcolor=white:x=(w-text_w)/2:y=h-130:box=1:"
            f"boxcolor=0x12245C@0.85:boxborderw=20")


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

    # (start, end, speed, caption)
    segs = [
        (max(0.0, m["login_page"] - 1.3), m["logged_in"] + 0.4, 1.0,
         "律師登入 · 案件權限隔離"),
        (m["logged_in"] + 0.4, m["analyze_clicked"] + 0.6, 1.0,
         "貼上審查意見書 · 機密先變代碼"),
        (m["analyze_clicked"] + 0.6, m["result_ready"] - 0.4, 5.5,
         "AI 分析中 · 地端模型 qwen2.5:7b（快轉）"),
        (m["result_ready"] - 0.4, m["results_done"] + 0.2, 1.0,
         "申復書草稿 · 引證驗證 · 期限試算"),
        (m["results_done"] + 0.2, m["end"], 1.0,
         "稽核鏈一鍵驗證 · 不可竄改"),
    ]

    files = []

    # brand cards from the HD deck export
    title_card = os.path.join(CARDS, "投影片1.PNG")
    end_card = os.path.join(CARDS, "投影片17.PNG")
    f = os.path.join(TMP, "00_title.mp4")
    run(["-loop", "1", "-t", "2.4", "-i", title_card,
         "-vf", "scale=1920:1080,fade=t=in:st=0:d=0.4", *ENC, f])
    files.append(f)

    for i, (a, b, speed, cap) in enumerate(segs, start=1):
        f = os.path.join(TMP, f"{i:02d}_seg.mp4")
        vf = f"scale=1920:1080,setpts=PTS/{speed},{caption_filter(cap)}"
        # -ss BEFORE -i: accurate input seek with PTS reset to 0, so the
        # setpts speed-up doesn't shift the trim window.
        run(["-ss", f"{a:.2f}", "-t", f"{b - a:.2f}", "-i", raw,
             "-vf", vf, *ENC, f])
        files.append(f)
        print(f"seg{i}: {a:.1f}–{b:.1f}s ×{speed} → {(b - a) / speed:.1f}s  {cap}")

    f = os.path.join(TMP, "99_end.mp4")
    run(["-loop", "1", "-t", "3.4", "-i", end_card,
         "-vf", "scale=1920:1080,fade=t=out:st=2.9:d=0.5", *ENC, f])
    files.append(f)

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
