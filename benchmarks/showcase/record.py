"""Record hosted-execution runs for the showcase replay: frames, Jev's distributions, gates.

    python -m benchmarks.showcase.record --demo browse --output docs/assets/showcase
    python -m benchmarks.showcase.record --demo desktop --output docs/assets/showcase

Live and billable (a few US cents). Both demos use the synthetic local fixtures in
benchmarks/sites; nothing outside them is touched. Each demo writes OUTPUT/<demo>/trace.json
plus one image per observation. The recorder wraps the real surface and the real Jev client:
it only watches, so the run is the same one `jev-filter browse` / `desktop` would perform.
"""

import argparse
import base64
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from benchmarks.hosted import DESKTOP, PRICE_PER_MILLION_INPUT, serve

RECT_JS = """(() => {
  const e = window.__jevFilterAct && window.__jevFilterAct.nodes.get(%d);
  if (!e) return null;
  const r = e.getBoundingClientRect();
  return {x: r.x, y: r.y, w: r.width, h: r.height};
})()"""


class Recorder:
    def __init__(self, directory):
        self.dir = Path(directory)
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self.events = []
        self.frames = 0
        self.started = time.perf_counter()
        self.last_frame = None
        self.last_state = None

    def now(self):
        return round((time.perf_counter() - self.started) * 1000)

    def add(self, kind, **fields):
        self.events.append({"type": kind, "t": self.now(), **fields})

    def frame(self, data, suffix):
        self.frames += 1
        name = f"f{self.frames:03d}.{suffix}"
        (self.dir / name).write_bytes(data)
        self.last_frame = name
        return name


def decisions_recorder(recorder, decide):
    """Wrap the Jev client: keep the distributions the showcase draws, not the request text."""

    def wrapped(body):
        started = time.perf_counter()
        result = decide(body)
        latency = round((time.perf_counter() - started) * 1000)
        answers = result.get("answers", {})
        questions = body.get("questions", {})
        op = answers.get("operation", {})
        heads = {}
        for qid, question in questions.items():
            if not qid.endswith("_target") or qid not in answers:
                continue
            probabilities = answers[qid].get("probabilities", {})
            top = sorted(probabilities.items(), key=lambda kv: -kv[1])[:5]
            heads[qid[: -len("_target")].upper()] = [
                {
                    "option": key,
                    "label": str(question["criteria"].get(key, {}).get("element", key))[:90],
                    "p": round(p, 3),
                }
                for key, p in top
            ]
        operations = sorted((op.get("probabilities") or {}).items(), key=lambda kv: -kv[1])
        recorder.add(
            "decide",
            latency_ms=latency,
            input_tokens=(result.get("usage") or {}).get("input_tokens"),
            operation=op.get("choice"),
            operations=[{"op": k, "p": round(v, 3)} for k, v in operations[:5]],
            targets=heads,
            irreversible=answers.get("irreversible", {}).get("noul"),
            value=answers.get("type_value", {}).get("choice"),
            candidates=sum(
                len(q.get("criteria", {})) for k, q in questions.items() if k.endswith("_target")
            ),
        )
        return result

    return wrapped


class RecordingSurface:
    """Delegates everything to the real surface; records each observation and execution."""

    def __init__(self, inner, recorder, capture, rect_of, values):
        self.inner, self.rec, self.capture, self.rect_of, self.values = (
            inner,
            recorder,
            capture,
            rect_of,
            values,
        )

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def observe(self, *args, **kwargs):
        state = self.inner.observe(*args, **kwargs)
        frame = self.capture()
        self.rec.last_state = state
        self.rec.add(
            "observe",
            frame=frame,
            url=state.get("url"),
            title=state.get("title"),
            controls=len([a for a in state.get("actions", []) if "node" in a]),
        )
        return state

    def act(self, action, page, text=None):
        rect = self.rect_of(action)
        shown = None
        if text is not None:
            sensitive = any(
                isinstance(v, dict) and v.get("sensitive") and v.get("value") == text
                for v in self.values.values()
            )
            shown = "[sensitive]" if sensitive or action.get("sensitive") else text
        self.rec.add(
            "act",
            frame=self.rec.last_frame,
            action={k: action.get(k) for k in ("id", "kind", "label", "role") if action.get(k)},
            rect=rect,
            text=shown,
        )
        return self.inner.act(action, page, text=text)

    def rect_for_id(self, action_id):
        for action in (self.rec.last_state or {}).get("actions", []):
            if action.get("id") == action_id:
                return self.rect_of(action)
        return None


def finish(recorder, surface, run, result):
    pending = result.get("pending") or {}
    recorder.add(
        "finish",
        frame=recorder.last_frame,
        status=result["status"],
        reason=result.get("reason"),
        pending={k: pending.get(k) for k in ("label", "role", "kind") if pending.get(k)},
        pending_rect=surface.rect_for_id(pending.get("id")) if pending.get("id") else None,
        irreversible_probability=result.get("irreversible_probability"),
        confirm_token=("…" + result["confirm_token"][-6:]) if result.get("confirm_token") else None,
        verification=result.get("verification"),
        steps=result.get("steps"),
        requests=result.get("requests"),
        input_tokens=(result.get("usage") or {}).get("input_tokens"),
    )


def write_trace(recorder, meta):
    tokens = sum(e.get("input_tokens") or 0 for e in recorder.events if e["type"] == "decide")
    requests = sum(1 for e in recorder.events if e["type"] == "decide")
    latencies = sorted(e["latency_ms"] for e in recorder.events if e["type"] == "decide")
    meta["summary"] = {
        "requests": requests,
        "input_tokens": tokens,
        "input_usd": round(tokens * PRICE_PER_MILLION_INPUT / 1e6, 5),
        "elapsed_ms": recorder.now(),
        "jev_p50_ms": latencies[len(latencies) // 2] if latencies else None,
        "actions": sum(1 for e in recorder.events if e["type"] == "act"),
    }
    meta["events"] = recorder.events
    (recorder.dir / "trace.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return meta["summary"]


# -- browser -----------------------------------------------------------------------------------
def record_browse(output):
    from jev_context.act.browser import CDPPage
    from jev_context.act.kernel import Run
    from jev_context.provider import Client

    goal = "Buy the cheapest in-stock red shoes in size 42"
    values = {"query": "red shoes"}
    server, base = serve()
    server.handle_error = lambda request, address: None  # the browser closing a socket is not news
    recorder = Recorder(Path(output) / "browse")
    client = Client(pooled=True)
    decide = decisions_recorder(recorder, client.call)
    page = CDPPage(url=base + "/index.html", headless=True, viewport=(960, 600))
    try:

        def capture():
            data = base64.b64decode(
                page.cmd("Page.captureScreenshot", {"format": "jpeg", "quality": 82})["data"]
            )
            return recorder.frame(data, "jpg")

        def rect_of(action):
            if "node" not in action:
                return None
            rect = page.evaluate(RECT_JS % int(action["node"]))
            return {k: round(v) for k, v in rect.items()} if rect else None

        surface = RecordingSurface(page, recorder, capture, rect_of, values)
        recorder.add("start", goal=goal)
        run = Run(surface, goal, decide=decide, values=values)
        result = run.run()
        finish(recorder, surface, run, result)
        if result["status"] == "needs_confirmation":
            recorder.add("approve", label=(result.get("pending") or {}).get("label"))
            resumed = Run(
                surface,
                goal,
                decide=decide,
                values=values,
                confirm=result["confirm_token"],
                verify_text="order has been placed",
            )
            final = resumed.run()
            finish(recorder, surface, resumed, final)
        summary = write_trace(
            recorder,
            {
                "demo": "browse",
                "goal": goal,
                "values": values,
                "surface": "Chromium, headless, over DevTools",
                "viewport": [960, 600],
                "site": "synthetic shop fixture (benchmarks/sites/shop)",
            },
        )
    finally:
        page.close(close_browser=True)
        client.close()
        server.shutdown()
    return summary


# -- desktop -----------------------------------------------------------------------------------
def frame_insets(hwnd):
    """Physical pixels between GetWindowRect and the visible (DWM extended) frame."""
    import ctypes
    from ctypes import wintypes

    user32, dwm = ctypes.WinDLL("user32"), ctypes.WinDLL("dwmapi")
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    dwm.DwmGetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    outer, inner = wintypes.RECT(), wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(outer)):
        return 0, 0, 0, 0
    if dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(inner), ctypes.sizeof(inner)):
        return 0, 0, 0, 0
    return (
        max(0, inner.left - outer.left),
        max(0, inner.top - outer.top),
        max(0, outer.right - inner.right),
        max(0, outer.bottom - inner.bottom),
    )


def record_desktop(output):
    import mss.tools

    from jev_context.act.desktop import DesktopSurface
    from jev_context.act.desktop_windows import WindowsBackend, _rect
    from jev_context.act.kernel import Run
    from jev_context.act.ocr import _crop, _grab_window
    from jev_context.provider import Client

    recorder = Recorder(Path(output) / "desktop")
    client = Client(pooled=True)
    decide = decisions_recorder(recorder, client.call)
    scenes = [
        (
            "Set the customer name to Ada Lovelace, choose the Pro plan, turn on the weekly "
            "report, and save the profile",
            {"name": "Ada Lovelace"},
            "saved Ada Lovelace / Pro / weekly=True",
        ),
        ("Delete all records", {}, None),
    ]
    try:
        for index, (goal, values, verify) in enumerate(scenes):
            title = f"Invoice Tool {int(time.time()) % 100000}{index}"
            process = subprocess.Popen(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(DESKTOP / "fixture.ps1"),
                    title,
                ]
            )
            try:
                backend = WindowsBackend(window=f"^{title}$")
                inner = DesktopSurface(backend)
                geometry = {}

                def capture():
                    hwnd = backend.window_info()["hwnd"]
                    grabbed = _grab_window(hwnd)
                    if grabbed is None:
                        return recorder.last_frame
                    rgb, size, origin, scale = grabbed
                    # GetWindowRect includes the invisible resize border (about 8 px); crop to
                    # the visible frame and move the origin so target rectangles stay aligned.
                    left, top, right, bottom = (round(v / scale) for v in frame_insets(hwnd))
                    if left or top or right or bottom:
                        box = (left, top, size[0] - right, size[1] - bottom)
                        rgb = _crop(rgb, size, box)
                        size = (box[2] - box[0], box[3] - box[1])
                        origin = (origin[0] + left * scale, origin[1] + top * scale)
                    geometry.update(origin=origin, scale=scale, size=size)
                    name = f"f{recorder.frames + 1:03d}.png"
                    mss.tools.to_png(rgb, size, output=str(recorder.dir / name))
                    recorder.frames += 1
                    recorder.last_frame = name
                    return name

                def rect_of(action):
                    if action.get("kind") == "select":
                        # The drop-down list is a separate popup window the capture does not
                        # include; point at the combo box that owns the option instead.
                        owner = action["label"].split(" → ")[0]
                        for other in (recorder.last_state or {}).get("actions", []):
                            if other.get("kind") == "click" and other.get("label") in (
                                f"Open {owner}",
                                owner,
                            ):
                                action = other
                                break
                    control = inner.nodes.get(action.get("node")) if "node" in action else None
                    if control is None or not geometry:
                        return None
                    left, top, right, bottom = _rect(control)
                    (ox, oy), scale = geometry["origin"], geometry["scale"]
                    return {
                        "x": round((left - ox) / scale),
                        "y": round((top - oy) / scale),
                        "w": round((right - left) / scale),
                        "h": round((bottom - top) / scale),
                    }

                surface = RecordingSurface(inner, recorder, capture, rect_of, values)
                recorder.add("start", goal=goal, scene=index)
                run = Run(surface, goal, decide=decide, values=values, verify_text=verify)
                result = run.run()
                finish(recorder, surface, run, result)
                recorder.add("size", size=geometry.get("size"))
            finally:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True
                )
        summary = write_trace(
            recorder,
            {
                "demo": "desktop",
                "goal": scenes[0][0],
                "surface": "Windows UI Automation (WinForms fixture)",
                "site": "synthetic WinForms fixture (benchmarks/sites/desktop/fixture.ps1)",
            },
        )
    finally:
        client.close()
    return summary


# -- survey ------------------------------------------------------------------------------------
def record_survey(output, n=2000):
    """One real `survey` run over generated tickets; keeps the report and ground-truth accuracy."""
    import contextlib
    import io
    import tempfile

    from benchmarks.survey_data import SPEC, generate, score
    from jev_context import survey

    records = generate(n)
    work = Path(tempfile.mkdtemp(prefix="jev-showcase-"))
    try:
        tickets = work / "tickets.jsonl"
        tickets.write_text(
            "\n".join(
                json.dumps({k: v for k, v in r.items() if k != "truth"}, ensure_ascii=False)
                for r in records
            ),
            encoding="utf-8",
        )
        spec = work / "survey.json"
        spec.write_text(json.dumps(SPEC), encoding="utf-8")
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = survey.main(["--input", str(tickets), "--spec", str(spec)])
        report = json.loads(stdout.getvalue())
        archive = Path(report.pop("archive"))
        answers = json.loads(archive.read_text(encoding="utf-8"))["answers"]
        archive.unlink()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    target = Path(output) / "survey"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    spam = sum(1 for r in records if r["truth"]["spam"])
    result = {
        "demo": "survey",
        "records": n,
        "spam_records": spam,
        "spec": SPEC,
        "exit_code": code,
        "accuracy": score(records, answers),
        "report": report,
    }
    (target / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return {
        "records": n,
        "requests": report["requests"],
        "input_tokens": report["usage"]["input_tokens"],
        "input_usd": report["estimated_input_usd"],
        "elapsed_ms": report["elapsed_ms"],
        "accuracy": {k: v["accuracy"] for k, v in result["accuracy"].items()},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--demo", choices=["browse", "desktop", "survey"], required=True)
    parser.add_argument("--output", default="docs/assets/showcase")
    args = parser.parse_args(argv)
    recorders = {"browse": record_browse, "desktop": record_desktop, "survey": record_survey}
    summary = recorders[args.demo](args.output)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    sys.exit(main())
