"""Build a small bilingual static documentation site from the maintained Markdown."""

import html
import re
import shutil
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site"
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir()
for directory in ("docs/assets", "examples", "schemas", "benchmarks"):
    shutil.copytree(ROOT / directory, OUT / directory, ignore=shutil.ignore_patterns("__pycache__"))
for name in ("LICENSE", "NOTICE"):
    shutil.copy2(ROOT / name, OUT / name)
nav = [
    ("index", "Overview", "文档首页"),
    ("getting-started", "Get started", "快速开始"),
    ("agent-quickstart", "Agent quickstart", "Agent 快速接入"),
    ("recipes", "Recipes", "任务配方"),
    ("hosted-execution", "Hosted execution", "托管执行"),
    ("showcase", "Recorded runs", "录制回放"),
    ("agents", "Agent integration", "Agent 完整接入"),
    ("integrations", "JavaScript & MCP", "JavaScript 与 MCP"),
    ("context-contract", "Context contract", "上下文契约"),
    ("cli", "CLI reference", "命令参考"),
    ("benchmarks", "Benchmarks", "测试与数据"),
    ("architecture", "Architecture", "架构"),
    ("distribution", "Distribution", "发行包"),
    ("development", "Development", "开发与保护"),
]
css = (ROOT / "docs/assets/docs.css").read_text(encoding="utf-8")
(OUT / "style.css").write_text(css, encoding="utf-8")
for source in [*ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md")]:
    rel = source.relative_to(ROOT)
    target = OUT / rel.with_suffix(".html")
    target.parent.mkdir(parents=True, exist_ok=True)
    cn = ".zh-CN." in source.name
    locale = ".zh-CN" if cn else ""
    prefix = "../" if rel.parts[0] == "docs" else ""
    text = source.read_text(encoding="utf-8")
    text = text.replace("<details>", '<details markdown="1">')
    title = next((line[2:] for line in text.splitlines() if line.startswith("# ")), "Jev Filter")
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "md_in_html"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )
    body = re.sub(
        r'(href=")([^"#]*?)\.md(#[^"]*)?"',
        lambda m: m[0] if "://" in m[2] else m[1] + m[2] + ".html" + (m[3] or "") + '"',
        body,
    )
    other = source.name.replace(".zh-CN", "") if cn else source.stem + ".zh-CN.md"
    other_url = (
        Path(other).with_suffix(".html").name
        if source.with_name(other).exists()
        else prefix + "docs/index" + ("" if cn else ".zh-CN") + ".html"
    )
    links = "".join(
        f'<a class="{"active" if rel.name == slug + locale + ".md" else ""}" href="{prefix}docs/{slug}{locale}.html">{zh if cn else en}</a>'
        for slug, en, zh in nav
    )
    home_class = " home" if rel.name.startswith("index.") else ""
    description = (
        "Jev Filter：把大量工具输出变成有证据的类型化判断，接入 CLI、Python 与 AI agent。"
        if cn
        else "Jev Filter turns large tool outputs into typed decisions with traceable evidence for AI agents."
    )
    output = f'''<!doctype html><html lang="{"zh-CN" if cn else "en"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="{html.escape(description)}"><title>{html.escape(title)} · Jev Filter</title><meta property="og:type" content="website"><meta property="og:title" content="{html.escape(title)} · Jev Filter"><meta property="og:description" content="{html.escape(description)}"><meta property="og:image" content="https://apixly-ai.github.io/jev-filter/docs/assets/social-preview{locale}.png"><meta name="twitter:card" content="summary_large_image"><link rel="stylesheet" href="{prefix}style.css"></head><body><header class="top"><a class="brand" href="{prefix}docs/index{locale}.html">jev<span>-filter</span></a><nav class="topnav"><a href="{other_url}">{"English" if cn else "简体中文"}</a><a class="github" href="https://github.com/apixly-ai/jev-filter">GitHub ↗</a></nav></header><div class="layout"><aside><p>{"使用与参考" if cn else "GUIDES & REFERENCE"}</p>{links}</aside><article class="content{home_class}">{body}<footer><span>Apixly · MIT · {"与 TypeSafe 独立的开源项目" if cn else "Independent of TypeSafe"}</span><a href="https://github.com/apixly-ai/jev-filter/releases">{"版本与构建来源 ↗" if cn else "Releases & provenance ↗"}</a></footer></article></div></body></html>'''
    target.write_text(output, encoding="utf-8")
(OUT / "index.html").write_text(
    '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=docs/index.html"><a href="docs/index.html">Jev Filter documentation</a></html>',
    encoding="utf-8",
)
(OUT / ".nojekyll").touch()
print("Built bilingual documentation in site/")
