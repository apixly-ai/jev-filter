"""CLI for hosted execution: ``browse`` (act on a web goal), ``extract`` (structured page data).

stdout carries a compact packet; the full step history, decision distributions and page
observations go to a private archive file, like every other Jev Filter command.
"""

import argparse
import json
import sys
import time
from pathlib import Path

from .. import analysis
from . import space


def load_values(path, pairs):
    values = {}
    if path:
        raw = sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("--values must be a JSON object")
        values.update(data)
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise ValueError("--value expects KEY=VALUE")
        values[key] = value
    for key, spec in values.items():
        if not isinstance(key, str) or not key:
            raise ValueError("value names must be nonempty strings")
        if isinstance(spec, dict):
            if "value" not in spec:
                raise ValueError(f"value {key!r} needs a 'value' field")
        elif not isinstance(spec, (str, int, float)):
            raise ValueError(f"value {key!r} must be a string or object")
    return values


def jev_decider():
    from ..provider import Client

    client = Client(pooled=True)

    def decide(body):
        return client.call(body)

    decide.client = client
    return decide


def open_page(args):
    from .browser import CamofoxPage, CDPPage

    if args.transport == "camofox":
        if not args.session:
            raise ValueError("camofox transport needs --session")
        return CamofoxPage(args.session, tab=args.tab, url=args.url)
    if getattr(args, "target_id", None) and not args.cdp_port:
        raise ValueError("--target-id needs --cdp-port")
    page = CDPPage(
        None,
        port=args.cdp_port,
        target_id=getattr(args, "target_id", None),
        executable=args.browser_executable,
        headless=not args.headful,
        dialogs="accept" if getattr(args, "accept_dialogs", False) else "dismiss",
    )
    if args.url:
        try:
            page.navigate(args.url)
        except Exception:
            page.close()
            raise
    return page


def add_browser_args(cmd):
    cmd.add_argument(
        "--url", help="Start URL (required unless attaching to an existing Camofox tab)"
    )
    cmd.add_argument("--transport", choices=["cdp", "camofox"], default="cdp")
    cmd.add_argument(
        "--cdp-port", type=int, help="Attach to an already running Chromium on this loopback port"
    )
    cmd.add_argument(
        "--browser-executable",
        help="Chrome/Edge/Chromium path (else JEV_BROWSER_EXECUTABLE or auto)",
    )
    cmd.add_argument("--headful", action="store_true", help="Show the launched browser window")
    cmd.add_argument("--session", help="Camofox session name")
    cmd.add_argument("--tab", help="Existing Camofox tab id")
    cmd.add_argument(
        "--target-id", help="Existing DevTools target (tab) to attach to; needs --cdp-port"
    )


def compact(result):
    keep = (
        "status",
        "ok",
        "goal",
        "steps",
        "decisions",
        "stale_decisions",
        "terminal_overrides",
        "requests",
        "usage",
        "usage_complete",
        "elapsed_ms",
        "final",
        "verification",
        "pending",
        "reason",
        "confirm_token",
        "irreversible_probability",
        "field",
        "fields",
        "supplied",
        "origin",
        "error",
        "budget",
        "last_confidence",
        "transport",
        "archive",
        "dialogs",
        "session",
        "confirmed",
    )
    packet = {k: result[k] for k in keep if result.get(k) is not None}
    packet["trace"] = [
        {
            k: h.get(k)
            for k in ("step", "operation", "action", "page_changed", "value_key", "skipped")
            if h.get(k) is not None
        }
        for h in result.get("history", [])
    ]
    return packet


def run_goal(surface, args, tool, allowed):
    """Shared loop wrapper for browser and desktop surfaces."""
    from ..cli import save_archive
    from ..stats import record
    from .kernel import Run
    from .text import from_environment

    values = load_values(args.values, args.value)
    if not 1 <= args.max_steps <= 500 or not 1 <= args.max_decisions <= 1000:
        raise ValueError("budgets out of range")
    helper = from_environment() if args.text_model else None
    if args.text_model and helper is None:
        raise ValueError(
            "--text-model needs JEV_TEXT_BASE_URL, JEV_TEXT_API_KEY and JEV_TEXT_MODEL"
        )
    decide = jev_decider()
    started = time.perf_counter()
    session = None
    try:
        run = Run(
            surface,
            args.goal,
            decide=decide,
            values=values,
            max_steps=args.max_steps,
            max_decisions=args.max_decisions,
            allow_irreversible=args.allow_irreversible,
            irreversible_threshold=args.irreversible_threshold,
            allowed_origins=allowed,
            text_helper=helper,
            model=args.model,
            observe_limit=args.limit,
            confirm=args.confirm,
            verify_text=args.verify_text,
            verify_url=getattr(args, "verify_url", None),
            verify_question=args.verify_question,
            continue_after_confirm=args.continue_after_confirm,
            dry_run=getattr(args, "dry_run", False),
        )
        result = run.run()
        result["transport"] = surface.name
        if getattr(surface, "dialogs", None):
            result["dialogs"] = surface.dialogs
        result["decision_log"] = run.decisions
    finally:
        if args.keep_open and hasattr(surface, "detach"):
            session = surface.detach()
        elif args.keep_open:
            session = {"camofox_tab": surface.tab} if hasattr(surface, "tab") else {"kept": True}
        elif getattr(args, "close_browser", False) and surface.name == "cdp":
            surface.close(close_browser=True)
        else:
            surface.close()
        decide.client.close()
    if session:
        result["session"] = session
    result["elapsed_ms"] = round((time.perf_counter() - started) * 1000)
    result["archive"] = save_archive({"tool": tool, "result": result})
    packet = compact(result)
    rendered = json.dumps(packet, ensure_ascii=False, indent=2)
    record(tool, None, rendered + "\n", {**result, "complete": result["ok"]}, comparable=False)
    print(rendered)
    return 0 if result["ok"] else 2


def run_browse(args):
    from .browser import origin_of

    attached = (args.transport == "camofox" and args.tab) or getattr(args, "target_id", None)
    if not args.url and not attached:
        raise ValueError("--url is required")
    allowed = list(args.allow_origin or [])
    if args.url and not args.any_origin:
        allowed.append(origin_of(args.url))
    elif not args.any_origin and not allowed:
        allowed = ["initial"]
    page = open_page(args)
    return run_goal(page, args, "browse", None if args.any_origin else allowed)


def open_desktop(args):
    import shlex

    from .desktop import DesktopSurface, open_backend
    from .ocr import open_ocr

    if not (args.window or args.process or args.launch):
        raise ValueError("desktop needs --window, --process or --launch")
    launch = shlex.split(args.launch, posix=sys.platform != "win32") if args.launch else None
    backend = open_backend(
        window=args.window, process=args.process, launch=launch, timeout=args.timeout
    )
    try:
        ocr = open_ocr(args.ocr)
    except Exception:
        backend.close()
        raise
    surface = DesktopSurface(
        backend,
        ocr=ocr,
        ocr_min_actions=2 if args.ocr == "auto" else 10**6,
        allow_sensitive=getattr(args, "allow_sensitive_app", False),
    )
    if args.ocr == "on":
        surface.ocr_min_actions = 10**6
    surface.name = "desktop-" + sys.platform
    return surface


def run_desktop(args):
    if args.list:
        from .desktop import list_windows

        print(json.dumps({"windows": list_windows()}, ensure_ascii=False, indent=2))
        return 0
    if not args.goal:
        raise ValueError("--goal is required")
    surface = open_desktop(args)
    return run_goal(surface, args, "desktop", None)


def run_extract(args):
    from ..tools import analyze_records

    spec = json.loads(Path(args.analysis).read_text(encoding="utf-8")) if args.analysis else None
    spec = analysis.validate(spec)
    admission = analysis.context_admission(spec)
    if admission:
        print(analysis.render(admission, spec))
        return 2
    page = open_page(args)
    started = time.perf_counter()
    try:
        data = page.extract(scope=args.scope, limit=args.max_records)
    finally:
        if not args.keep_open:
            page.close()
    if not data or data.get("scope_missing"):
        print(json.dumps({"ok": False, "error": "scope_missing"}))
        return 2
    records = [
        {k: v for k, v in r.items() if k in ("id", "text", "kind", "section", "href", "caption")}
        for r in data["records"]
    ]
    collection = {
        "ok": True,
        "url": data.get("url"),
        "title": data.get("title"),
        "truncated": bool(data.get("omitted")),
        "omitted": data.get("omitted", 0),
    }
    if not records:
        print(
            json.dumps(
                {"ok": True, "complete": True, "selected_ids": [], "review_ids": [], "records": 0}
            )
        )
        return 0
    result = analyze_records(records, args.task, spec, collection, args.workers, args.budget_chars)
    result.update(
        tool="extract",
        url=data.get("url"),
        records=len(records),
        elapsed_ms=round((time.perf_counter() - started) * 1000),
    )
    rendered = analysis.render(result, spec)
    from ..stats import record

    record("extract", json.dumps(records, ensure_ascii=False), rendered + "\n", result)
    print(rendered)
    return 0 if result["ok"] and result["complete"] else 2


def add_goal_args(cmd, goal_required=True):
    cmd.add_argument("--goal", required=goal_required)
    cmd.add_argument("--values", help="JSON object of named values to type (path or -)")
    cmd.add_argument("--value", action="append", help="Named value KEY=VALUE (repeatable)")
    cmd.add_argument(
        "--allow-irreversible", action="store_true", help="Execute pay/send/delete-like actions"
    )
    cmd.add_argument("--irreversible-threshold", type=float, default=0.5)
    cmd.add_argument("--confirm", help="Confirm token from a previous needs_confirmation result")
    cmd.add_argument(
        "--continue-after-confirm",
        action="store_true",
        help="Keep working toward the goal after executing a confirmed action",
    )
    cmd.add_argument("--max-steps", type=int, default=60)
    cmd.add_argument("--max-decisions", type=int, default=120)
    cmd.add_argument("--verify-text", help="Text that must appear in the final state")
    cmd.add_argument("--verify-question", help="Yes/no question Jev must affirm on the final state")
    cmd.add_argument(
        "--text-model", action="store_true", help="Use JEV_TEXT_* model for unsupplied field text"
    )
    cmd.add_argument("--model", default=space.DEFAULT_MODEL)
    cmd.add_argument("--limit", type=int, default=250, help="Maximum observed controls per step")
    cmd.add_argument(
        "--keep-open", action="store_true", help="Leave the tab, browser or launched app running"
    )
    cmd.add_argument(
        "--dry-run", action="store_true", help="Observe and decide one step; execute nothing"
    )


def main(argv=None):
    parser = argparse.ArgumentParser(prog="jev-filter", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    browse = sub.add_parser(
        "browse", help="Let Jev drive a browser toward a goal; the program executes"
    )
    add_browser_args(browse)
    add_goal_args(browse)
    browse.add_argument(
        "--allow-origin", action="append", help="Additional origin the run may visit"
    )
    browse.add_argument(
        "--any-origin", action="store_true", help="Do not restrict navigation origins"
    )
    browse.add_argument(
        "--accept-dialogs", action="store_true", help="Accept alert/beforeunload dialogs"
    )
    browse.add_argument("--verify-url", help="Regex the final URL must match")
    browse.add_argument(
        "--close-browser", action="store_true", help="Close an attached browser after the run"
    )
    desktop = sub.add_parser(
        "desktop", help="Let Jev drive one desktop application toward a goal (Windows/macOS)"
    )
    add_goal_args(desktop, goal_required=False)
    desktop.add_argument("--window", help="Regex matching the target window title")
    desktop.add_argument("--process", help="Target process/application name")
    desktop.add_argument("--launch", help="Command that starts the target application")
    desktop.add_argument("--timeout", type=float, default=15, help="Seconds to wait for the window")
    desktop.add_argument(
        "--ocr",
        choices=["auto", "on", "off"],
        default="auto",
        help="OCR fallback when accessibility exposes too few controls",
    )
    desktop.add_argument("--list", action="store_true", help="List candidate windows and exit")
    desktop.add_argument(
        "--allow-sensitive-app",
        action="store_true",
        help="Allow terminals, credential managers and system settings as targets",
    )
    extract = sub.add_parser(
        "extract", help="Structure a page into records and let Jev select relevant ones"
    )
    add_browser_args(extract)
    extract.add_argument("--model", default=space.DEFAULT_MODEL)
    extract.add_argument("--limit", type=int, default=250)
    extract.add_argument("--task", required=True)
    extract.add_argument("--analysis", help="Decision spec (same contract as query)")
    extract.add_argument("--scope", help="CSS scope for extraction")
    extract.add_argument("--max-records", type=int, default=500)
    extract.add_argument("--workers", default="auto")
    extract.add_argument("--budget-chars", type=int, default=4000)
    extract.add_argument("--keep-open", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "browse":
        return run_browse(args)
    if args.command == "desktop":
        return run_desktop(args)
    return run_extract(args)
