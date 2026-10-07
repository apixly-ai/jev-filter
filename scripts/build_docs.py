"""Build a bilingual static site with canonical, source-backed documentation."""

import html
import json
import posixpath
import re
import shutil
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit
from xml.etree import ElementTree

import markdown
from markdown.extensions.toc import slugify_unicode

ROOT = Path(__file__).resolve().parents[1]
SITE_URL = "https://apixly-ai.github.io/jev-filter/"
REPOSITORY_URL = "https://github.com/apixly-ai/jev-filter"
NAV = [
    ("index", "Overview", "文档首页"),
    ("getting-started", "Get started", "快速开始"),
    ("agent-quickstart", "Agent quickstart", "Agent 快速接入"),
    ("search-result-filtering", "Filter search results", "筛选搜索结果"),
    ("semantic-code-search", "Semantic code search", "语义代码搜索"),
    ("log-triage", "Log triage", "日志归类"),
    ("faq", "FAQ", "常见问题"),
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
DESCRIPTIONS = {
    "index.md": (
        "Jev Filter filters retrieved records, code candidates and logs into compact, typed "
        "evidence packets for AI agents, with recoverable originals."
    ),
    "index.zh-CN.md": "Jev Filter 为 AI Agent 筛选检索结果、代码候选与日志，返回精简、类型化的证据包，并保留可回查原文。",
    "benchmarks.md": (
        "Reproducible synthetic benchmarks for Jev Filter: expected IDs, context bytes, "
        "whole-operation timing, model usage, failures and trade-offs."
    ),
    "benchmarks.zh-CN.md": "Jev Filter 可复现合成测试：期望 ID、返回上下文字节、整段耗时、模型用量、失败与适用限制。",
}


class PageText(HTMLParser):
    """Read actual headings and prose, excluding images and link-only navigation."""

    def __init__(self):
        super().__init__()
        self.paragraphs = []
        self.current = None
        self.nonlink = []
        self.links = 0
        self.link_depth = 0
        self.heading = None
        self.title = ""

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            fields = dict(attrs)
            self.current = [] if "home-actions" not in fields.get("class", "").split() else None
            self.nonlink = []
            self.links = 0
        if tag == "a":
            self.link_depth += 1
            if self.current is not None:
                self.links += 1
        if tag == "h1" and not self.title:
            self.heading = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)
            if self.link_depth == 0:
                self.nonlink.append(data)
        if self.heading is not None:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self.link_depth = max(0, self.link_depth - 1)
        if tag == "h1" and self.heading is not None:
            self.title = re.sub(r"\s+", " ", "".join(self.heading)).strip()
            self.heading = None
        if tag == "p" and self.current is not None:
            text = re.sub(r"\s+", " ", "".join(self.current)).strip()
            only_links = self.links and re.fullmatch(r"[\s·|•—–\-→↗,:;/]*", "".join(self.nonlink))
            navigation = only_links
            if (
                text
                and not navigation
                and not re.fullmatch(r"(?:English|简体中文|中文文档首页|中文使用说明|·|\s)+", text)
            ):
                self.paragraphs.append(text)
            self.current = None


def description_for(source, content, title):
    if source.parent.name == "docs" and source.name in DESCRIPTIONS:
        return DESCRIPTIONS[source.name]
    text = next(
        (p for p in content.paragraphs if len(p) >= 12), f"{title} — Jev Filter documentation."
    )
    if len(text) > 200:
        text = text[:197].rsplit(" ", 1)[0] if " " in text[:197] else text[:197]
        text += "…"
    return text


def canonical_path(path):
    if path.as_posix() in {"docs/index.html", "index.html"}:
        return Path("index.html")
    if path.as_posix() == "docs/index.zh-CN.html":
        return Path("index.zh-CN.html")
    return path


def absolute_url(path):
    path = canonical_path(path)
    return SITE_URL + ("" if path.as_posix() == "index.html" else path.as_posix())


def relative_url(path, target):
    if path.as_posix() == "index.html":
        return posixpath.relpath(".", target.parent.as_posix()) + "/"
    return posixpath.relpath(path.as_posix(), target.parent.as_posix())


def rebase_links(body, source, target):
    """Resolve Markdown-origin links before rendering a page at its canonical root."""

    def rewrite(match):
        url = urlsplit(html.unescape(match[3]))
        if url.scheme or url.netloc or not url.path or url.path.startswith("/"):
            return match[0]
        path = Path(posixpath.normpath(posixpath.join(source.parent.as_posix(), unquote(url.path))))
        if path.suffix == ".md":
            path = path.with_suffix(".html")
        path = canonical_path(path)
        rebased = relative_url(path, target)
        value = urlunsplit(("", "", rebased, url.query, url.fragment))
        return match[1] + match[2] + html.escape(value, quote=True) + match[2]

    return re.sub(r"""((?:href|src)=)(["'])(.*?)\2""", rewrite, body, flags=re.S)


def project_version(root):
    # Python 3.10 is supported; the project's version is a literal TOML string.
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    project = re.search(r"(?ms)^\[project\]\s*\n(.*?)(?=^\[|\Z)", text)
    match = re.search(r'^version\s*=\s*"([^"]+)"', project[1], re.M) if project else None
    if not match:
        raise ValueError("Project version is required for source-code metadata")
    return match[1]


def render_page(root, source, target, version):
    rel = source.relative_to(root)
    cn = ".zh-CN." in source.name
    locale = ".zh-CN" if cn else ""
    text = source.read_text(encoding="utf-8").replace("<details>", '<details markdown="1">')
    body = markdown.markdown(
        text,
        extensions=["tables", "fenced_code", "toc", "md_in_html"],
        extension_configs={"toc": {"slugify": slugify_unicode}},
    )
    content = PageText()
    content.feed(body)
    title = content.title or "Jev Filter"
    description = description_for(source, content, title)
    body = rebase_links(body, rel, target)
    other_name = source.name.replace(".zh-CN", "") if cn else source.stem + ".zh-CN.md"
    other_source = source.with_name(other_name)
    other_path = (
        canonical_path(other_source.relative_to(root).with_suffix(".html"))
        if other_source.exists()
        else Path("index" + ("" if cn else ".zh-CN") + ".html")
    )
    other_url = relative_url(other_path, target)
    home_path = Path("index" + locale + ".html")
    links = "".join(
        f'<a class="{"active" if rel.name == slug + locale + ".md" else ""}" '
        f'href="{relative_url(canonical_path(Path("docs") / (slug + locale + ".html")), target)}">'
        f"{zh if cn else en}</a>"
        for slug, en, zh in NAV
        if (root / "docs" / (slug + locale + ".md")).exists()
    )
    canonical = absolute_url(target)
    alternates = ""
    if other_source.exists():
        english = absolute_url(other_path) if cn else canonical
        chinese = canonical if cn else absolute_url(other_path)
        alternates = (
            f'<link rel="alternate" hreflang="en" href="{english}">'
            f'<link rel="alternate" hreflang="zh-CN" href="{chinese}">'
            f'<link rel="alternate" hreflang="x-default" href="{english}">'
        )
    home = rel.parent == Path("docs") and rel.stem in {"index", "index.zh-CN"}
    schema = ""
    if home:
        data = {
            "@context": "https://schema.org",
            "@type": "SoftwareSourceCode",
            "name": "Jev Filter",
            "description": description,
            "url": canonical,
            "codeRepository": REPOSITORY_URL,
            "license": "https://opensource.org/license/mit/",
            "version": version,
            "programmingLanguage": "Python",
        }
        payload = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
        schema = f'<script type="application/ld+json">{payload}</script>'
    safe_title = html.escape(title)
    safe_description = html.escape(description, quote=True)
    css = relative_url(Path("style.css"), target)
    return f'''<!doctype html><html lang="{"zh-CN" if cn else "en"}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="generator" content="Jev Filter documentation">
<meta name="description" content="{safe_description}">
<title>{safe_title} · Jev Filter</title>
<link rel="canonical" href="{canonical}">{alternates}
<meta property="og:type" content="website"><meta property="og:url" content="{canonical}">
<meta property="og:title" content="{safe_title} · Jev Filter">
<meta property="og:description" content="{safe_description}">
<meta property="og:image" content="{SITE_URL}docs/assets/social-preview{locale}.png">
<meta name="twitter:card" content="summary_large_image">
<link rel="stylesheet" href="{css}">{schema}
</head><body><header class="top"><a class="brand" href="{relative_url(home_path, target)}">jev<span>-filter</span></a><nav class="topnav"><a href="{other_url}">{"English" if cn else "简体中文"}</a><a class="github" href="{REPOSITORY_URL}">GitHub ↗</a></nav></header><div class="layout"><aside><p>{"使用与参考" if cn else "GUIDES & REFERENCE"}</p>{links}</aside><article class="content{" home" if home else ""}">{body}<footer><span>Apixly · MIT · {"与 TypeSafe 独立的开源项目" if cn else "Independent of TypeSafe"}</span><a href="{relative_url(Path("sitemap.xml"), target)}">{"网站地图" if cn else "Sitemap"}</a><a href="{REPOSITORY_URL}/releases">{"版本与构建来源 ↗" if cn else "Releases & provenance ↗"}</a></footer></article></div></body></html>'''


def build(root=ROOT):
    out = root / "site"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir()
    for directory in ("docs/assets", "examples", "schemas", "benchmarks"):
        shutil.copytree(
            root / directory, out / directory, ignore=shutil.ignore_patterns("__pycache__")
        )
    for name in ("LICENSE", "NOTICE"):
        shutil.copy2(root / name, out / name)
    (out / "style.css").write_text(
        (root / "docs/assets/docs.css").read_text(encoding="utf-8"), encoding="utf-8"
    )
    version = project_version(root)
    # Contributor instructions are not user documentation. Nested research and copied
    # benchmark HTML remain evidence artifacts, never inferred sitemap candidates.
    sources = [
        *(p for p in root.glob("*.md") if p.name != "AGENTS.md"),
        *(root / "docs").glob("*.md"),
    ]
    locations = set()
    for source in sources:
        target = source.relative_to(root).with_suffix(".html")
        paths = [target]
        if target.as_posix() in {"docs/index.html", "docs/index.zh-CN.html"}:
            paths.append(canonical_path(target))
        for path in paths:
            output = out / path
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(render_page(root, source, path, version), encoding="utf-8")
        locations.add(absolute_url(target))
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ElementTree.register_namespace("", namespace)
    sitemap = ElementTree.Element(f"{{{namespace}}}urlset")
    for url in sorted(locations):
        entry = ElementTree.SubElement(sitemap, f"{{{namespace}}}url")
        ElementTree.SubElement(entry, f"{{{namespace}}}loc").text = url
    ElementTree.ElementTree(sitemap).write(
        out / "sitemap.xml", encoding="utf-8", xml_declaration=True
    )
    key_file = root / "scripts/indexnow-key.txt"
    if key_file.exists():
        key = key_file.read_text(encoding="utf-8").strip()
        if not re.fullmatch(r"[a-fA-F0-9]{32}", key):
            raise ValueError("IndexNow public verification key must be 32 hexadecimal characters")
        (out / f"{key}.txt").write_text(key, encoding="utf-8")
    # Provider-issued ownership proof files are public, byte-preserved artifacts;
    # they are not Markdown pages or sitemap entries.
    verification = root / "docs/site-verification"
    if verification.exists():
        for proof in sorted(verification.iterdir()):
            if not proof.is_file():
                continue
            target = out / proof.name
            if target.exists():
                raise ValueError(
                    f"Site verification proof conflicts with generated file: {proof.name}"
                )
            shutil.copyfile(proof, target)
    (out / ".nojekyll").touch()
    return out


if __name__ == "__main__":
    build()
    print("Built bilingual documentation in site/")
