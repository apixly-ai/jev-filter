#!/usr/bin/env python3
"""Read-only skill routes to one Jev Filter invocation; no extra inference layer."""

import argparse
import os
import re
import shutil
from pathlib import Path


def bounded_workers(value):
    count = int(value)
    if not 1 <= count <= 30:
        raise argparse.ArgumentTypeError("workers must be 1..30")
    return count


def existing_root(value):
    root = Path(value).resolve()
    if not root.is_dir():
        raise argparse.ArgumentTypeError("root must be an existing directory")
    return str(root)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    routes = result.add_subparsers(dest="route", required=True)
    for name in ("records", "code", "diff", "logs"):
        route = routes.add_parser(name)
        route.add_argument("--task", required=True)
        route.add_argument("--analysis", required=name == "records")
        route.add_argument("--workers", type=bounded_workers, default=4)
        route.add_argument("--budget-chars", type=int, default=4000)
        if name in ("records", "logs"):
            route.add_argument("--input", required=True)
        if name in ("code", "diff"):
            route.add_argument("--root", type=existing_root, required=True)
            route.add_argument("--limit", type=int, default=40)
        if name == "records":
            route.add_argument("--mode", choices=["filter", "analyze", "choose"], default="filter")
            route.add_argument("--plan", action="store_true")
        if name == "code":
            route.add_argument("--pattern")
            route.add_argument("--query")
            route.add_argument("--expand-callers", action="store_true")
            route.add_argument("--max-files", type=int, default=2000)
        if name == "diff":
            scope = route.add_mutually_exclusive_group(required=True)
            scope.add_argument("--base")
            scope.add_argument("--staged", action="store_true")
            scope.add_argument("--unstaged", action="store_true")
            route.add_argument("--head")
        if name == "logs":
            route.add_argument("--group-by", default="request_id")
    survey = routes.add_parser("survey")
    survey.add_argument("--input", required=True)
    survey.add_argument("--spec", required=True)
    survey.add_argument("--labels")
    survey.add_argument("--workers", type=bounded_workers, default=4)
    survey.add_argument("--max-records", type=int, default=1000)
    survey.add_argument("--max-requests", type=int, default=30)
    survey.add_argument("--max-usd", type=float, default=0.05)
    survey.add_argument("--dry-run", action="store_true")
    evaluation = routes.add_parser("eval")
    evaluation.add_argument("--input", required=True)
    return result


def build_command(argv):
    cli = parser()
    args = cli.parse_args(argv)
    if args.route == "eval":
        return ["eval", "--input", args.input]
    if args.route == "survey":
        if not 1 <= args.max_records <= 10000 or not 1 <= args.max_requests <= 1000:
            cli.error("survey record/request limits must be positive and bounded")
        if not 0 < args.max_usd <= 100:
            cli.error("survey max-usd must be positive and bounded")
        command = [
            "survey",
            "--input",
            args.input,
            "--spec",
            args.spec,
            "--workers",
            str(args.workers),
            "--max-records",
            str(args.max_records),
            "--max-requests",
            str(args.max_requests),
            "--max-usd",
            str(args.max_usd),
        ]
        if args.labels:
            command += ["--labels", args.labels]
        if args.dry_run:
            command.append("--dry-run")
        return command
    if not args.task.strip() or not 1 <= args.budget_chars <= 100000:
        cli.error("provide a nonempty task and bounded excerpt budget")
    verb = {"records": "query", "code": "code-search", "diff": "diff-review", "logs": "triage"}[
        args.route
    ]
    command = [
        verb,
        "--task",
        args.task,
        "--workers",
        str(args.workers),
        "--budget-chars",
        str(args.budget_chars),
    ]
    if args.analysis:
        command += ["--analysis", args.analysis]
    if args.route in ("records", "logs"):
        command += ["--input", args.input]
    if args.route in ("code", "diff"):
        if not 1 <= args.limit <= 2000:
            cli.error("limit must be 1..2000")
        command += ["--root", args.root, "--limit", str(args.limit)]
    if args.route == "records":
        command += ["--mode", args.mode, "--diagnostics"]
        if args.plan:
            command.append("--plan")
    if args.route == "code":
        if not args.pattern and not args.query:
            cli.error("code requires a pattern or lexical recall query")
        if not 1 <= args.max_files <= 2000:
            cli.error("max-files must be 1..2000")
        pattern = args.pattern if args.pattern else re.escape(args.query)
        command += ["--max-files", str(args.max_files)]
        if args.query:
            command += ["--query", args.query]
        if args.expand_callers:
            command.append("--expand-callers")
        command += ["--", pattern]
    if args.route == "diff":
        if args.head and not args.base:
            cli.error("head requires base")
        command += (
            ["--base", args.base] if args.base else ["--staged" if args.staged else "--unstaged"]
        )
        if args.head:
            command += ["--head", args.head]
    if args.route == "logs":
        command += ["--group-by", args.group_by]
    return command


def main(argv=None):
    import sys

    command = build_command(sys.argv[1:] if argv is None else argv)
    executable = shutil.which("jev-filter")
    if not executable:
        raise SystemExit("jev-filter is not installed; install the maintained package first")
    # Replace this process. Canonical CLI stdout, stdin, exit 2, signals and cleanup
    # remain with the existing runtime; this helper neither parses nor repeats inference.
    os.execv(executable, [executable, *command])


if __name__ == "__main__":
    main()
