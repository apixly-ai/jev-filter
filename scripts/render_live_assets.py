"""Render current data charts and social previews; preserve the maintained SVG hero."""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/assets"
DATA = json.loads((ROOT / "benchmarks/results/2026-10-04-live-operations-summary.json").read_text())
INK, MUTED, MINT, VIOLET, AMBER = "#14243c", "#62748c", "#12856b", "#7660cc", "#b27018"
available = {font.name for font in font_manager.fontManager.ttflist}
CHINESE = next(
    (
        name
        for name in ("Noto Sans CJK SC", "PingFang SC", "Heiti TC", "Arial Unicode MS")
        if name in available
    ),
    None,
)
if CHINESE is None:
    raise RuntimeError("A Chinese font is required for bilingual artwork")


def chart(cn=False):
    plt.rcParams.update(
        {
            "font.family": CHINESE if cn else "DejaVu Sans",
            "text.color": INK,
            "axes.labelcolor": MUTED,
            "xtick.color": MUTED,
            "ytick.color": INK,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.spines.bottom": False,
        }
    )
    figure, axes = plt.subplots(1, 3, figsize=(14.1, 6.0))
    figure.patch.set_facecolor("#f9fbff")
    figure.subplots_adjust(left=0.145, right=0.95, top=0.68, bottom=0.23, wspace=0.25)
    figure.text(
        0.045,
        0.92,
        "把更多注意力留给推理。" if cn else "Give reasoning more room.",
        fontsize=26,
        weight="bold",
    )
    figure.text(
        0.045,
        0.855,
        "2026-10-04 · 24 次真实 agent 运行 · 三个合成场景 · 两个主模型 · 每臂两次"
        if cn
        else "2026-10-04 · 24 real agent runs · 3 synthetic scenarios · 2 primary models · 2 repeats per arm",
        fontsize=11.5,
        color=MUTED,
    )
    columns = [
        (
            "context_bytes_reduction_pct",
            "工具返回上下文减少" if cn else "Returned tool context reduction",
            MINT,
        ),
        (
            "cold_cost_reduction_pct",
            "冷输入 API 等价费用减少" if cn else "Cold API-equivalent savings",
            VIOLET,
        ),
        (
            "latency_change_pct",
            "整段平均耗时变化" if cn else "Mean whole-operation time change",
            AMBER,
        ),
    ]
    labels = [
        ("Luna" if "luna" in row["model"] else "Astra") + " / " + row["case"]
        for row in DATA["rows"]
    ]
    for index, (axis, (field, title, color)) in enumerate(zip(axes, columns)):
        values = [row[field] for row in DATA["rows"]]
        colors = (
            [MINT if value < 0 else AMBER for value in values]
            if field == "latency_change_pct"
            else [color if value >= 0 else AMBER for value in values]
        )
        axis.set_facecolor("#f9fbff")
        axis.barh(range(len(values)), values, height=0.56, color=colors)
        axis.invert_yaxis()
        axis.set_yticks(range(len(values)), labels if index == 0 else [""] * len(values))
        axis.tick_params(length=0, labelsize=11)
        axis.set_title(title, loc="left", fontsize=12, weight="bold", pad=16)
        axis.axvline(0, color="#cbd6e4", linewidth=0.8)
        axis.set_axisbelow(True)
        axis.xaxis.grid(color="#e5ecf4")
        if field == "context_bytes_reduction_pct":
            axis.set_xlim(0, 124)
        elif field == "cold_cost_reduction_pct":
            axis.set_xlim(-10, 33)
        else:
            axis.set_xlim(-29, 30)
        for y, value in enumerate(values):
            axis.text(
                value + (1.5 if value >= 0 else -1.5),
                y,
                f"{value:+.1f}%" if field != "context_bytes_reduction_pct" else f"{value:.1f}%",
                va="center",
                ha="left" if value >= 0 else "right",
                fontsize=11,
                weight="bold",
            )
    figure.text(
        0.045,
        0.142,
        "选中 ID：24/24 正确 · 完整完成：原文 11/12，过滤 12/12 · 六个单元中五个变慢"
        if cn
        else "Expected ID sets: 24/24 · Complete: raw 11/12, filtered 12/12 · Five of six cells were slower",
        fontsize=11.5,
        color=INK,
        weight="bold",
    )
    figure.text(
        0.045,
        0.085,
        "费用为 API 等价估算，订阅实际账单未知。工具返回量不是整个 prompt；小型合成样本不保证普遍收益。"
        if cn
        else "Cost is an API-equivalent estimate; subscription billing is unknown. Tool bytes are not the entire prompt.",
        fontsize=10.5,
        color=MUTED,
    )
    figure.text(
        0.045,
        0.043,
        "逐次数据与费用假设见 benchmarks/results/2026-10-04-live-operations-summary.json。"
        if cn
        else "Small synthetic sample. Per-run data and pricing assumptions: benchmarks/results/2026-10-04-live-operations-summary.json",
        fontsize=9.5,
        color=MUTED,
    )
    suffix = ".zh-CN" if cn else ""
    figure.savefig(OUT / f"operations-live{suffix}.png", dpi=160)
    figure.savefig(OUT / f"operations-live{suffix}.svg")
    svg_path = OUT / f"operations-live{suffix}.svg"
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines())
        + "\n",
        encoding="utf-8",
    )
    plt.close(figure)


def social_images():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 640}, device_scale_factor=1)
        for suffix in ("", ".zh-CN"):
            svg = (OUT / f"hero{suffix}.svg").read_text()
            page.set_content(
                "<style>body{margin:0;padding:40px;background:#080e1c;box-sizing:border-box}svg{display:block}</style>"
                + svg
            )
            page.screenshot(path=str(OUT / f"social-preview{suffix}.png"))
        browser.close()


def speed_chart(cn=False):
    """Plot the measured parallel baseline, not an inferred primary-model speedup."""
    batch = json.loads(
        (ROOT / "benchmarks/results/2026-10-04-live-batching.json").read_text(encoding="utf-8")
    )["summary"]
    baseline, treatment = batch["single_parallel"], batch["batch_parallel"]
    speedup = baseline["mean_ms"] / treatment["mean_ms"]
    reduction = 100 * (1 - treatment["mean_ms"] / baseline["mean_ms"])
    input_reduction = 100 * (1 - treatment["known_input_tokens"] / baseline["known_input_tokens"])
    plt.rcParams.update({"font.family": CHINESE if cn else "DejaVu Sans"})
    figure = plt.figure(figsize=(12, 5.4), facecolor="#f9fbff")
    axis = figure.add_axes((0.235, 0.30, 0.51, 0.35), facecolor="#f9fbff")
    figure.text(
        0.045,
        0.90,
        "把重复判断，一批做完。" if cn else "Judge the batch. Get back to reasoning.",
        color=INK,
        fontsize=25,
        weight="bold",
    )
    figure.text(
        0.045,
        0.815,
        "96 条合成记录 × 2 个语义条件 · 同一 Jev 模型 · 每臂 3 次 · 2026-10-04"
        if cn
        else "96 synthetic records × 2 semantic predicates · Same Jev model · 3 repeats per arm · 2026-10-04",
        color=MUTED,
        fontsize=11,
    )
    seconds = [baseline["mean_ms"] / 1000, treatment["mean_ms"] / 1000]
    labels = (
        ["单条并发", "自动合批并发"]
        if cn
        else ["Single-record parallel", "Automatic batch + parallel"]
    )
    axis.barh([1, 0], seconds, height=0.42, color=["#9badc5", MINT])
    axis.set_yticks([1, 0], labels)
    axis.set_xlim(0, 4)
    axis.set_xticks([0, 1, 2, 3, 4])
    axis.set_xlabel(
        "Jev 筛选全过程均值（秒）" if cn else "Mean Jev filtering operation (seconds)", color=MUTED
    )
    axis.tick_params(length=0, labelsize=11)
    axis.set_axisbelow(True)
    axis.xaxis.grid(color="#e1e8f1")
    for spine in axis.spines.values():
        spine.set_visible(False)
    for y, value in zip([1, 0], seconds):
        axis.text(
            value + 0.08, y, f"{value:.2f} s", va="center", color=INK, weight="bold", fontsize=14
        )
    figure.text(0.79, 0.57, f"{speedup:.2f}×", color=MINT, fontsize=47, weight="bold")
    figure.text(
        0.795, 0.495, "合批处理速度" if cn else "batch speed", color=INK, fontsize=15, weight="bold"
    )
    figure.text(
        0.795,
        0.427,
        f"{reduction:.1f}% " + ("耗时减少" if cn else "less time"),
        color=MUTED,
        fontsize=12,
    )
    figure.text(
        0.045,
        0.195,
        f"12/12 次结果精确 · 合批输入 tokens 减少 {input_reduction:.1f}% · 不使用结果缓存"
        if cn
        else f"12/12 exact runs · {input_reduction:.1f}% fewer batched input tokens · No result cache",
        color=INK,
        fontsize=12,
        weight="bold",
    )
    figure.text(
        0.045,
        0.13,
        "并发上限 12；合批仅需 2 个请求。这是 Jev 阶段的对照，不是对主模型或整轮 agent 的加速承诺。"
        if cn
        else "Worker cap 12; batching needed 2 requests. Jev-stage comparison, not primary-model or whole-agent speed.",
        color=MUTED,
        fontsize=10.5,
    )
    figure.text(
        0.045,
        0.075,
        "另测完整 agent 任务：六个单元中五个变慢。原始数据：benchmarks/results/2026-10-04-live-batching.json"
        if cn
        else "Separate whole-agent test: five of six cells slower. Source: benchmarks/results/2026-10-04-live-batching.json",
        color=MUTED,
        fontsize=10,
    )
    suffix = ".zh-CN" if cn else ""
    figure.savefig(OUT / f"speed-live{suffix}.png", dpi=160)
    figure.savefig(OUT / f"speed-live{suffix}.svg")
    svg_path = OUT / f"speed-live{suffix}.svg"
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines())
        + "\n",
        encoding="utf-8",
    )
    plt.close(figure)


def selection_speed_chart(cn=False):
    """Keep execution-path timing and equal-output quality beside the headline."""
    data = json.loads(
        (ROOT / "benchmarks/results/2026-10-04-live-selection-speed.json").read_text(
            encoding="utf-8"
        )
    )
    keys = ["jev", "gpt-5.6-luna", "gpt-6-astra"]
    rows = [data["summary"][key] for key in keys]
    assert all(row["complete_correct_runs"] == row["runs"] == 3 for row in rows)
    seconds = [row["median_ms"] / 1000 for row in rows]
    plt.rcParams.update({"font.family": CHINESE if cn else "DejaVu Sans"})
    figure = plt.figure(figsize=(12, 5.4), facecolor="#f9fbff")
    axis = figure.add_axes((0.235, 0.29, 0.52, 0.38), facecolor="#f9fbff")
    figure.text(
        0.045,
        0.90,
        "重复判断，走更快的路径。" if cn else "A fast path for repeated judgments.",
        color=INK,
        fontsize=25,
        weight="bold",
    )
    figure.text(
        0.045,
        0.815,
        "96 条合成记录 · 同样条件、同样完整 ID 集 · 每臂 3 次 · 2026-10-04"
        if cn
        else "96 synthetic records · Same criteria, same complete ID-set output · 3 repeats per arm · 2026-10-04",
        color=MUTED,
        fontsize=11,
    )
    positions = [2, 1, 0]
    axis.barh(positions, seconds, height=0.48, color=[MINT, "#9badc5", "#b2adc9"])
    axis.set_yticks(positions, ["Jev API", "Luna · Codex CLI", "Astra · Codex CLI"])
    axis.set_xlim(0, 18)
    axis.set_xticks([0, 5, 10, 15])
    axis.set_xlabel(
        "筛选工具路径中位耗时（秒）" if cn else "Median screening execution path (seconds)",
        color=MUTED,
    )
    axis.tick_params(length=0, labelsize=11)
    axis.set_axisbelow(True)
    axis.xaxis.grid(color="#e1e8f1")
    for spine in axis.spines.values():
        spine.set_visible(False)
    for y, value in zip(positions, seconds):
        axis.text(
            value + 0.35, y, f"{value:.2f} s", va="center", color=INK, weight="bold", fontsize=14
        )
    figure.text(0.795, 0.555, f"{seconds[0]:.2f} s", color=MINT, fontsize=40, weight="bold")
    figure.text(
        0.8,
        0.48,
        "完整筛选结果" if cn else "complete selection",
        color=INK,
        fontsize=14,
        weight="bold",
    )
    figure.text(0.8, 0.407, "9/9 次结果精确" if cn else "9/9 exact runs", color=MUTED, fontsize=12)
    figure.text(
        0.045,
        0.185,
        "零误选 · 零漏选 · 零待复核 · 不使用结果缓存 · 实际用量全部已知"
        if cn
        else "Zero false positives, misses or reviews · No result cache · Complete measured usage",
        color=INK,
        fontsize=12,
        weight="bold",
    )
    figure.text(
        0.045,
        0.12,
        "Jev API 对比已登录 Codex CLI；后者包含启动与 agent 开销。不是原生推理或整轮 agent 加速对照。"
        if cn
        else "Jev API vs signed-in Codex CLI, including startup and agent overhead. Not isolated native inference or whole-agent speed.",
        color=MUTED,
        fontsize=9.7,
    )
    figure.text(
        0.045,
        0.063,
        "每臂三次仅为小样本验证。原始数据：benchmarks/results/2026-10-04-live-selection-speed.json"
        if cn
        else "Three repeats are a smoke sample. Source: benchmarks/results/2026-10-04-live-selection-speed.json",
        color=MUTED,
        fontsize=10,
    )
    suffix = ".zh-CN" if cn else ""
    figure.savefig(OUT / f"selection-speed-live{suffix}.png", dpi=160)
    figure.savefig(OUT / f"selection-speed-live{suffix}.svg")
    svg_path = OUT / f"selection-speed-live{suffix}.svg"
    svg_path.write_text(
        "\n".join(line.rstrip() for line in svg_path.read_text(encoding="utf-8").splitlines())
        + "\n",
        encoding="utf-8",
    )
    plt.close(figure)


chart(False)
chart(True)
speed_chart(False)
speed_chart(True)
selection_speed_chart(False)
selection_speed_chart(True)
social_images()
print("Rendered current bilingual charts and social images from maintained hero and measured data.")
