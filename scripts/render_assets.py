"""Render repository-owned diagrams and data-derived benchmark charts."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets"
OUT.mkdir(exist_ok=True)
INK = "#122039"
MUTED = "#64748b"
MINT = "#12846b"
PURPLE = "#7958d6"
AMBER = "#b66515"
plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 12,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.spines.bottom": False,
        "text.color": INK,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": INK,
        "figure.facecolor": "#f8fafc",
        "axes.facecolor": "#f8fafc",
        "svg.fonttype": "none",
    }
)
data = json.loads((ROOT / "benchmarks/results/2026-09-22-live.json").read_text(encoding="utf-8"))
names = ["single_serial", "batch_serial", "single_parallel", "batch_parallel"]
labels = ["Single · serial", "Batch · serial", "Single · parallel", "Batch + parallel"]
colors = ["#cbd5e1", PURPLE, "#94a3b8", MINT]
fig, axes = plt.subplots(1, 2, figsize=(13, 5.3), gridspec_kw={"width_ratios": [1.2, 1]})
fig.subplots_adjust(left=0.16, right=0.95, top=0.7, bottom=0.2, wspace=0.35)
fig.text(0.055, 0.91, "Less repeated input. Faster batched work.", fontsize=23, weight="bold")
fig.text(
    0.055,
    0.84,
    "Public Jev benchmark · 96 records × 2 predicates · 2 repetitions per arm",
    fontsize=12,
    color=MUTED,
)
for ax, key, divisor, title, limit, suffix in [
    (axes[0], "mean_ms", 1000, "Mean elapsed time", 46, "s"),
    (axes[1], "known_input_tokens", 1000, "Input tokens · both repetitions", 162, "k"),
]:
    vals = [data["summary"][name][key] / divisor for name in names]
    ax.barh(range(4), vals, color=colors, height=0.55)
    ax.invert_yaxis()
    ax.set_yticks(range(4), labels if ax == axes[0] else [""] * 4)
    ax.tick_params(axis="both", length=0)
    ax.set_xlim(0, limit)
    ax.set_title(title, loc="left", fontsize=13, pad=15, weight="bold")
    ax.set_axisbelow(True)
    ax.xaxis.grid(color="#e2e8f0")
    ax.set_xticks([0, 20, 40] if suffix == "s" else [0, 70, 140])
    for i, v in enumerate(vals):
        ax.text(
            v + limit * 0.025,
            i,
            f"{v:.2f}{suffix}" if suffix == "s" else f"{v:.1f}{suffix}",
            va="center",
            fontsize=12,
            weight="bold",
        )
fig.text(
    0.055, 0.09, "56.5% fewer input tokens with batching", color=MINT, weight="bold", fontsize=14
)
fig.text(
    0.54, 0.09, "32.4% faster vs single-record parallel", color=MINT, weight="bold", fontsize=14
)
fig.text(
    0.055,
    0.035,
    "8/8 exact runs · no result cache · cap 30 · Jev-stage measurement, not whole-agent speedup",
    fontsize=10,
    color=MUTED,
)
fig.savefig(OUT / "batch-benchmark.png", dpi=180)
fig.savefig(OUT / "batch-benchmark.svg")
plt.close(fig)
fig, axes = plt.subplots(1, 3, figsize=(13, 4.9))
fig.subplots_adjust(left=0.14, right=0.95, top=0.68, bottom=0.2, wspace=0.4)
fig.text(
    0.055,
    0.91,
    "Smaller context. Potential savings. A latency trade-off.",
    fontsize=21,
    weight="bold",
)
fig.text(
    0.055,
    0.83,
    "Historical private prototype · 3 fixed synthetic workflows · 2 paired runs · not this release",
    fontsize=11,
    color=MUTED,
)
for ax, vals, title, col in zip(
    axes,
    [[96.13, 88.47, 97.26], [20.58, 4.37, 25.18], [10.21, 4.02, 1.52]],
    ["Context reduction", "Cold API cost reduction", "Extra elapsed time"],
    [MINT, PURPLE, AMBER],
):
    ax.barh(range(3), vals, color=col, height=0.5)
    ax.invert_yaxis()
    ax.set_yticks(
        range(3), ["Code search", "Browser locate", "Log triage"] if ax == axes[0] else [""] * 3
    )
    ax.set_title(title, loc="left", fontsize=12, weight="bold", pad=15)
    ax.tick_params(length=0)
    ax.set_xlim(0, max(vals) * 1.38)
    for i, v in enumerate(vals):
        ax.text(v + max(vals) * 0.04, i, f"{v:.1f}%", va="center", weight="bold")
    ax.set_axisbelow(True)
    ax.xaxis.grid(color="#e2e8f0")
fig.text(
    0.055,
    0.09,
    "Cost = historical API-equivalent estimate. All three workflows were slower.",
    fontsize=12,
    color=AMBER,
    weight="bold",
)
fig.text(
    0.055,
    0.035,
    "Private raw traces are not published. See the report for scope and reproducibility limits.",
    fontsize=10,
    color=MUTED,
)
fig.savefig(OUT / "workflow-tradeoffs.png", dpi=180)
fig.savefig(OUT / "workflow-tradeoffs.svg")
plt.close(fig)
print("Rendered historical benchmark charts from checked-in data; maintained hero is unchanged.")

# Localized artwork uses the same data; no English paragraphs are mixed into Chinese pages.

available = {font.name for font in font_manager.fontManager.ttflist}
chinese_font = next(
    (
        name
        for name in ("Noto Sans CJK SC", "PingFang SC", "Heiti TC", "Arial Unicode MS")
        if name in available
    ),
    None,
)
if chinese_font:
    plt.rcParams["font.family"] = chinese_font
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.3), gridspec_kw={"width_ratios": [1.2, 1]})
    fig.subplots_adjust(left=0.16, right=0.95, top=0.7, bottom=0.2, wspace=0.35)
    fig.text(0.055, 0.91, "减少重复输入，让批量判断更高效", fontsize=23, weight="bold")
    fig.text(
        0.055,
        0.84,
        "公开 Jev 测试 · 96 条记录 × 2 个判断 · 每组重复 2 轮",
        fontsize=12,
        color=MUTED,
    )
    cn_labels = ["单条串行", "合批串行", "单条并发", "合批并发"]
    for ax, key, divisor, title, limit, suffix in [
        (axes[0], "mean_ms", 1000, "平均耗时", 46, " 秒"),
        (axes[1], "known_input_tokens", 1000, "输入 token · 两轮合计", 162, " 千"),
    ]:
        vals = [data["summary"][name][key] / divisor for name in names]
        ax.barh(range(4), vals, color=colors, height=0.55)
        ax.invert_yaxis()
        ax.set_yticks(range(4), cn_labels if ax == axes[0] else [""] * 4)
        ax.tick_params(axis="both", length=0)
        ax.set_xlim(0, limit)
        ax.set_title(title, loc="left", fontsize=13, pad=15, weight="bold")
        ax.set_axisbelow(True)
        ax.xaxis.grid(color="#e2e8f0")
        ax.set_xticks([0, 20, 40] if key == "mean_ms" else [0, 70, 140])
        for i, value in enumerate(vals):
            ax.text(
                value + limit * 0.025,
                i,
                f"{value:.2f}{suffix}" if key == "mean_ms" else f"{value:.1f}{suffix}",
                va="center",
                fontsize=12,
                weight="bold",
            )
    fig.text(0.055, 0.09, "合批减少 56.5% 输入 token", color=MINT, weight="bold", fontsize=14)
    fig.text(0.54, 0.09, "合批并发比单条并发快 32.4%", color=MINT, weight="bold", fontsize=14)
    fig.text(
        0.055,
        0.035,
        "8/8 组结果正确 · 不用结果缓存 · 并发上限 30 · 仅计 Jev 阶段，不代表整轮主模型收益",
        fontsize=10,
        color=MUTED,
    )
    fig.savefig(OUT / "batch-benchmark.zh-CN.png", dpi=180)
    fig.savefig(OUT / "batch-benchmark.zh-CN.svg")
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.9))
    fig.subplots_adjust(left=0.14, right=0.95, top=0.68, bottom=0.2, wspace=0.4)
    fig.text(0.055, 0.91, "上下文更少，费用可能下降，也可能更慢", fontsize=21, weight="bold")
    fig.text(
        0.055,
        0.83,
        "历史私有原型 · 3 条固定合成流程 · 每组配对 2 轮 · 非当前发行包实测",
        fontsize=11,
        color=MUTED,
    )
    for ax, vals, title, color in zip(
        axes,
        [[96.13, 88.47, 97.26], [20.58, 4.37, 25.18], [10.21, 4.02, 1.52]],
        ["上下文减少", "冷输入等价费用下降", "额外耗时"],
        [MINT, PURPLE, AMBER],
    ):
        ax.barh(range(3), vals, color=color, height=0.5)
        ax.invert_yaxis()
        ax.set_yticks(range(3), ["代码搜索", "网页定位", "日志分流"] if ax == axes[0] else [""] * 3)
        ax.set_title(title, loc="left", fontsize=12, weight="bold", pad=15)
        ax.tick_params(length=0)
        ax.set_xlim(0, max(vals) * 1.38)
        for i, value in enumerate(vals):
            ax.text(value + max(vals) * 0.04, i, f"{value:.1f}%", va="center", weight="bold")
        ax.set_axisbelow(True)
        ax.xaxis.grid(color="#e2e8f0")
    fig.text(
        0.055,
        0.09,
        "费用为历史 API 等价估算；三条流程都变慢了。",
        fontsize=12,
        color=AMBER,
        weight="bold",
    )
    fig.text(
        0.055,
        0.035,
        "私有原始轨迹未公开。测试范围、费用口径与复现限制见报告。",
        fontsize=10,
        color=MUTED,
    )
    fig.savefig(OUT / "workflow-tradeoffs.zh-CN.png", dpi=180)
    fig.savefig(OUT / "workflow-tradeoffs.zh-CN.svg")
    plt.close(fig)
else:
    raise RuntimeError(
        "Install a Chinese font (Noto Sans CJK SC recommended) to render localized charts"
    )
