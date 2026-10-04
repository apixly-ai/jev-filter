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
            "工具返回上下文减少" if cn else "Returned tool context less",
            MINT,
        ),
        (
            "cold_cost_reduction_pct",
            "冷输入 API 等价费用减少" if cn else "Cold API-equivalent cost less",
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


chart(False)
chart(True)
social_images()
print("Rendered current bilingual charts and social images from maintained hero and measured data.")
