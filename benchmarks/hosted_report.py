"""Summarize a hosted-execution benchmark JSON into English and Chinese Markdown tables.

python -m benchmarks.hosted_report benchmarks/results/2026-09-30-hosted.json
"""

import json
import statistics
import sys
from collections import defaultdict


def median(values):
    values = [v for v in values if v is not None]
    return round(statistics.median(values)) if values else None


def summarize(data):
    groups = defaultdict(list)
    for row in data["rows"]:
        if row.get("skipped") or row["line"] == "survey":
            continue
        groups[(row["line"], row["transport"], row["task"], row["variant"])].append(row)
    tasks = []
    for (line, transport, task, variant), rows in groups.items():
        tasks.append(
            {
                "line": line,
                "transport": transport,
                "task": task,
                "variant": variant,
                "expected": rows[0]["expected"],
                "passed": sum(r["passed"] for r in rows),
                "runs": len(rows),
                "steps": median(r["steps"] for r in rows),
                "requests": median(r["requests"] for r in rows),
                "elapsed_ms": median(r["elapsed_ms"] for r in rows),
                "input_tokens": median(r["input_tokens"] for r in rows),
                "jev_p50_ms": median((r.get("jev_latency_ms") or {}).get("p50") for r in rows),
                "statuses": sorted({r["status"] for r in rows}),
            }
        )
    surveys = [r for r in data["rows"] if r["line"] == "survey"]
    return tasks, surveys


def pct(value):
    return "–" if value is None else f"{value * 100:.1f}%"


def markdown(data, lang="en"):
    tasks, surveys = summarize(data)
    zh = lang == "zh"
    out = []
    head = (
        "| 线 | 传输 | 任务 | 期望 | 通过 | 步数中位 | 请求中位 | 耗时中位 | 输入 token 中位 | Jev p50 |"
        if zh
        else "| Line | Transport | Task | Expected | Passed | Median steps | Median requests | Median time | Median input tokens | Jev p50 |"
    )
    out += [head, "|---|---|---|---|---:|---:|---:|---:|---:|---:|"]
    for t in sorted(tasks, key=lambda t: (t["line"], t["transport"], t["variant"], t["task"])):
        name = t["task"] + (
            " (no gated note)"
            if t["variant"] != "default" and not zh
            else "（无门禁说明）"
            if t["variant"] != "default"
            else ""
        )
        seconds = f"{t['elapsed_ms'] / 1000:.1f} s" if t["elapsed_ms"] is not None else "–"
        out.append(
            f"| {t['line']} | {t['transport']} | {name} | `{t['expected']}` | {t['passed']}/{t['runs']} | "
            f"{t['steps']} | {t['requests']} | {seconds} | {t['input_tokens']:,} | {t['jev_p50_ms']} ms |"
        )
    out.append("")
    head = (
        "| 变体 | 记录 | 请求 | 输入 token | 输入费用 | 耗时 | 主题 | 情绪 | 退订意图 | 筛选 |"
        if zh
        else "| Variant | Records | Requests | Input tokens | Input USD | Time | Topic | Sentiment | Churn | Screen |"
    )
    out += [head, "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for s in surveys:
        acc = s["accuracy"]
        out.append(
            f"| {s['variant']} | {s['records']:,} | {s['requests']} | {s['input_tokens']:,} | ${s['input_usd']:.4f} | "
            f"{s['elapsed_ms'] / 1000:.1f} s | {pct((acc.get('topic') or {}).get('accuracy'))} | "
            f"{pct((acc.get('sentiment') or {}).get('accuracy'))} | {pct((acc.get('churn') or {}).get('accuracy'))} | "
            f"{pct((acc.get('screen') or {}).get('accuracy')) if acc.get('screen') else '–'} |"
        )
    return "\n".join(out)


def main():
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(markdown(data, sys.argv[2] if len(sys.argv) > 2 else "en"))


if __name__ == "__main__":
    main()
