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
    ("agents", "Integrations", "完整集成"),
    ("context-contract", "Context contract", "上下文契约"),
    ("cli", "CLI reference", "命令参考"),
    ("benchmarks", "Benchmarks", "测试与数据"),
    ("architecture", "Architecture", "架构"),
    ("distribution", "Distribution", "发行包"),
    ("development", "Development", "开发与保护"),
]
css = """*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:#172338;background:#f7f9fc;font:16px/1.75 system-ui,-apple-system,"PingFang SC",sans-serif}a{color:#126f61;text-decoration:none}a:hover{text-decoration:underline}.top{height:68px;background:#132039;color:white;display:flex;align-items:center;justify-content:space-between;padding:0 32px;position:sticky;top:0;z-index:2}.top a{color:#d8f4ea}.brand{font-size:23px;font-weight:750;letter-spacing:-.6px}.brand span{color:#86dec2}.topnav{display:flex;gap:22px;font-size:14px}.layout{max-width:1440px;margin:auto;display:grid;grid-template-columns:235px minmax(0,1fr);gap:36px;padding:36px 30px}aside{position:sticky;top:95px;align-self:start}aside p{font-size:11px;letter-spacing:2px;font-weight:700;color:#7a8799;margin:0 0 16px}aside a{display:block;color:#53627b;padding:8px 12px;border-radius:7px;font-size:14px}aside a.active{background:#e3f3ed;color:#126f61;font-weight:700}.content{min-width:0;background:white;border:1px solid #e4e9f0;border-radius:14px;padding:40px 48px;box-shadow:0 8px 30px #1a2d4510}h1{font-size:34px;letter-spacing:-1px;line-height:1.3;margin:0 0 24px}h2{font-size:24px;line-height:1.4;margin:40px 0 18px;padding-bottom:10px;border-bottom:1px solid #e8edf3}h3{font-size:18px}p,ul,ol{margin:0 0 20px}li+li{margin-top:8px}img{max-width:100%;height:auto;border-radius:8px}pre{background:#152239;color:#dce7f7;padding:22px;border-radius:10px;overflow:auto;font-size:13px;line-height:1.6}code{font-family:ui-monospace,SFMono-Regular,Consolas,monospace}p code,li code,td code{font-size:.88em;background:#eef2f7;padding:2px 5px;border-radius:4px}table{display:block;overflow:auto;max-width:100%;border-collapse:collapse;margin-bottom:24px;font-size:14px}th,td{padding:12px 14px;border:1px solid #e2e8f0;text-align:left}th{background:#f3f6fa}blockquote{margin:20px 0;padding:12px 20px;border-left:4px solid #86c9b6;background:#f1faf7;color:#486558}footer{color:#8692a3;font-size:12px;margin-top:40px;padding-top:16px;border-top:1px solid #e8edf3}.menu{display:none}@media(max-width:800px){.layout{display:block;padding:18px}.content{padding:24px 20px}aside{position:static;display:flex;overflow:auto;gap:4px;margin-bottom:18px}aside p{display:none}aside a{white-space:nowrap;font-size:12px;padding:6px 9px}.top{padding:0 20px}.topnav{gap:14px}.brand{font-size:20px}h1{font-size:28px}h2{font-size:22px}}"""
(OUT / "style.css").write_text(css, encoding="utf-8")
for source in [*ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md")]:
    rel = source.relative_to(ROOT)
    target = OUT / rel.with_suffix(".html")
    target.parent.mkdir(parents=True, exist_ok=True)
    cn = ".zh-CN." in source.name
    locale = ".zh-CN" if cn else ""
    prefix = "../" if rel.parts[0] == "docs" else ""
    text = source.read_text(encoding="utf-8")
    title = next((line[2:] for line in text.splitlines() if line.startswith("# ")), "Jev Filter")
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc"],
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
    output = f'''<!doctype html><html lang="{"zh-CN" if cn else "en"}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Jev Filter: task-aware tool-result filtering with reproducible benchmarks."><title>{html.escape(title)} · Jev Filter</title><link rel="stylesheet" href="{prefix}style.css"></head><body><header class="top"><a class="brand" href="{prefix}docs/index{locale}.html">jev<span>-filter</span></a><nav class="topnav"><a href="{other_url}">{"English" if cn else "简体中文"}</a><a href="https://github.com/apixly-ai/jev-filter">GitHub ↗</a></nav></header><div class="layout"><aside><p>{"使用与参考" if cn else "GUIDES & REFERENCE"}</p>{links}</aside><article class="content">{body}<footer>Apixly · MIT · {"与 TypeSafe 独立的开源项目" if cn else "Independent of TypeSafe"}</footer></article></div></body></html>'''
    target.write_text(output, encoding="utf-8")
(OUT / "index.html").write_text(
    '<!doctype html><html lang="en"><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=docs/index.html"><a href="docs/index.html">Jev Filter documentation</a></html>',
    encoding="utf-8",
)
(OUT / ".nojekyll").touch()
print("Built bilingual documentation in site/")
