"""Build the showcase replay data and export GIF/MP4/PNG from recorded runs.

    python -m benchmarks.showcase.render                 # data.js only
    python -m benchmarks.showcase.render --media         # also GIFs, MP4s and the survey PNG

Reads docs/assets/showcase/{browse,desktop}/trace.json and survey/report.json written by
benchmarks.showcase.record. --media needs Playwright's Chromium and ffmpeg on PATH. Every
frame is a screenshot of docs/assets/showcase/index.html?capture=1, so the page and the media
show the same thing.
"""

import argparse
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOW = ROOT / "docs" / "assets" / "showcase"
PRICE_PER_MILLION_INPUT = 0.042

TITLES = {
    "browse": {"en": "The browser, driven step by step", "zh": "逐步驱动浏览器"},
    "desktop": {"en": "A desktop app, same loop", "zh": "桌面应用，同样的循环"},
}
VERIFY = {"browse": "order has been placed", "desktop": "saved Ada Lovelace / Pro / weekly=True"}


def image_size(path):
    data = path.read_bytes()
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    i = 2
    while i < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        length = struct.unpack(">H", data[i + 2 : i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        i += 2 + length
    raise ValueError(f"unknown image format: {path}")


def compact(decide):
    if not decide:
        return None
    return {
        "latency_ms": decide["latency_ms"],
        "candidates": decide["candidates"],
        "operation": decide["operation"],
        "operations": decide["operations"],
        "targets": decide["targets"].get(decide["operation"], []),
        "irreversible": decide["irreversible"],
        "value": decide.get("value") if decide.get("value") not in (None, "NONE") else None,
    }


def slides(trace):
    out = [{"kind": "intro"}]
    totals = {"requests": 0, "tokens": 0, "usd": 0.0, "ms": 0}
    observed, decide, goal, n = None, None, trace["goal"], 0
    # Run time only: each scene counts from its start (target found) to its finish, so browser
    # start-up and application launches are excluded.
    clock = {"offset": 0, "start": 0, "last": 0}

    def snapshot(t):
        return {
            **totals,
            "usd": round(totals["tokens"] * PRICE_PER_MILLION_INPUT / 1e6, 5),
            "ms": clock["offset"] + t - clock["start"],
        }

    for e in trace["events"]:
        kind = e["type"]
        if kind == "start":
            if e.get("scene"):
                clock["offset"] += clock["last"] - clock["start"]
            clock["start"] = clock["last"] = e["t"]
            goal = e["goal"]
            if e.get("scene"):
                out.append({"kind": "scene", "goal": goal})
        elif kind == "observe":
            observed = e
        elif kind == "decide":
            decide = e
            totals["requests"] += 1
            totals["tokens"] += e.get("input_tokens") or 0
        elif kind == "act":
            n += 1
            out.append(
                {
                    "kind": "step",
                    "n": n,
                    "goal": goal,
                    "frame": e["frame"],
                    "url": (observed or {}).get("url"),
                    "title": (observed or {}).get("title"),
                    "rect": e.get("rect"),
                    "action": e["action"],
                    "text": e.get("text"),
                    "decide": compact(decide),
                    "totals": snapshot(e["t"]),
                }
            )
            decide = None
        elif kind == "finish":
            clock["last"] = e["t"]
            base = {
                "goal": goal,
                "frame": e["frame"],
                "url": (observed or {}).get("url"),
                "title": (observed or {}).get("title"),
                "totals": snapshot(e["t"]),
            }
            if e["status"] == "needs_confirmation":
                out.append(
                    {
                        **base,
                        "kind": "pause",
                        "rect": e.get("pending_rect"),
                        "pending": e.get("pending") or {},
                        "reason": e.get("reason"),
                        "irreversible_probability": e.get("irreversible_probability"),
                        "token": e.get("confirm_token"),
                        "decide": compact(decide),
                    }
                )
            elif e["status"] == "done":
                out.append({**base, "kind": "done", "verification": e.get("verification")})
            else:
                out.append({**base, "kind": "stop", "status": e["status"]})
            decide = None
    out.append({"kind": "outro"})
    return out, n, clock["offset"] + clock["last"] - clock["start"]


def build_data():
    demos = {}
    for name in ("browse", "desktop"):
        path = SHOW / name / "trace.json"
        if not path.exists():
            continue
        trace = json.loads(path.read_text(encoding="utf-8"))
        items, steps, run_ms = slides(trace)
        images = {}
        for s in items:
            if s.get("frame") and s["frame"] not in images:
                w, h = image_size(SHOW / name / s["frame"])
                images[s["frame"]] = {"w": w, "h": h}
        demos[name] = {
            "kind": "replay",
            "command": name,
            "dir": f"{name}/",
            "goal": trace["goal"],
            "title": TITLES[name],
            "verifyText": VERIFY[name],
            "summary": {**trace["summary"], "elapsed_ms": run_ms},
            "stepCount": steps,
            "images": images,
            "slides": items,
        }
    survey = SHOW / "survey" / "report.json"
    if survey.exists():
        data = json.loads(survey.read_text(encoding="utf-8"))
        demos["survey"] = {
            "kind": "dashboard",
            **{k: data[k] for k in ("records", "accuracy", "report")},
        }
    payload = {"recorded": "2026-09-30", "demos": demos}
    (SHOW / "data.js").write_text(
        "// Generated by benchmarks/showcase/render.py from recorded runs. Do not edit.\n"
        "window.JEV_SHOWCASE = " + json.dumps(payload, ensure_ascii=False, indent=1) + ";\n",
        encoding="utf-8",
    )
    return demos


def capture(demos, out_dir):
    from playwright.sync_api import sync_playwright

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required for --media")
    made = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
        for name, demo in demos.items():
            for lang, suffix in (("en", ""), ("zh", ".zh-CN")):
                page.goto((SHOW / "index.html").as_uri() + f"?capture=1&demo={name}&lang={lang}")
                page.wait_for_function("window.__showcase !== undefined")
                frames = page.evaluate("window.__showcase.frames()")
                work = Path(tempfile.mkdtemp(prefix="jev-frames-"))
                listing = []
                for k, f in enumerate(frames):
                    page.evaluate(f"window.__showcase.go({f['i']}, {f['phase']})")
                    page.wait_for_function(
                        "[...document.images].every(i => i.complete && i.naturalWidth > 0)"
                    )
                    page.wait_for_timeout(60)
                    png = work / f"p{k:03d}.png"
                    page.screenshot(path=str(png))
                    listing.append(f"file '{png.as_posix()}'\nduration {f['ms'] / 1000:.2f}")
                if demo["kind"] == "dashboard":
                    target = out_dir / f"{name}{suffix}.png"
                    shutil.copyfile(work / "p000.png", target)
                    made.append(target)
                    shutil.rmtree(work, ignore_errors=True)
                    continue
                listing.append(f"file '{(work / f'p{len(frames) - 1:03d}.png').as_posix()}'")
                total = sum(f["ms"] for f in frames) / 1000
                concat = work / "list.txt"
                concat.write_text("\n".join(listing) + "\n", encoding="utf-8")
                gif = out_dir / f"{name}{suffix}.gif"
                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-loglevel",
                        "error",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(concat),
                        "-vf",
                        "fps=10,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160:stats_mode=diff[p];"
                        "[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                        "-t",
                        f"{total:.2f}",
                        "-loop",
                        "0",
                        str(gif),
                    ],
                    check=True,
                )
                mp4 = out_dir / f"{name}{suffix}.mp4"
                subprocess.run(
                    [
                        ffmpeg,
                        "-y",
                        "-loglevel",
                        "error",
                        "-f",
                        "concat",
                        "-safe",
                        "0",
                        "-i",
                        str(concat),
                        "-vf",
                        "fps=25,format=yuv420p",
                        "-c:v",
                        "libx264",
                        "-crf",
                        "26",
                        "-preset",
                        "slow",
                        "-t",
                        f"{total:.2f}",
                        "-movflags",
                        "+faststart",
                        str(mp4),
                    ],
                    check=True,
                )
                made += [gif, mp4]
                shutil.rmtree(work, ignore_errors=True)
        browser.close()
    return made


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--media", action="store_true", help="export GIF/MP4/PNG (needs ffmpeg)")
    args = parser.parse_args(argv)
    demos = build_data()
    print(
        "data.js:", ", ".join(f"{k} ({len(v.get('slides', []))} slides)" for k, v in demos.items())
    )
    if args.media:
        for path in capture(demos, SHOW):
            print(f"{path.relative_to(ROOT).as_posix()}: {path.stat().st_size / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
