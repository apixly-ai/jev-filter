"""Portable static-site discovery checks using only synthetic local Markdown."""

import json
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree

import pytest

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://apixly-ai.github.io/jev-filter/"
SLUGS = (
    "index",
    "getting-started",
    "agent-quickstart",
    "search-result-filtering",
    "semantic-code-search",
    "log-triage",
    "faq",
    "recipes",
    "hosted-execution",
    "showcase",
    "agents",
    "integrations",
    "context-contract",
    "cli",
    "benchmarks",
    "architecture",
    "distribution",
    "development",
)


class ParsedPage(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.links = []
        self.meta = {}
        self.scripts = []
        self._json = False
        self._title = False
        self.title = ""
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if tag in {"a", "link", "img"}:
            self.links.append((tag, fields))
        if tag == "meta":
            self.meta[fields.get("name", fields.get("property"))] = fields.get("content")
        if tag == "script" and fields.get("type") == "application/ld+json":
            self._json = True
        if tag == "title":
            self._title = True

    def handle_data(self, data):
        if self._json:
            self.scripts.append(json.loads(data))
        if self._title:
            self.title += data

    def handle_endtag(self, tag):
        if tag == "script":
            self._json = False
        if tag == "title":
            self._title = False


@pytest.fixture
def built_site(tmp_path):
    fixture = tmp_path / "project"
    (fixture / "scripts").mkdir(parents=True)
    for script in ("build_docs.py", "check_docs.py"):
        shutil.copy2(ROOT / "scripts" / script, fixture / "scripts" / script)
    (fixture / "scripts/indexnow-key.txt").write_text("a" * 32 + "\n", encoding="utf-8")
    for folder in ("docs/assets", "examples", "schemas", "benchmarks/research"):
        (fixture / folder).mkdir(parents=True)
    (fixture / "docs/assets/docs.css").write_text("body { color: black; }", encoding="utf-8")
    for suffix in ("", ".zh-CN"):
        (fixture / f"docs/assets/social-preview{suffix}.png").write_bytes(b"fixture")
    (fixture / "docs/assets/hero.svg").write_text("<svg/>", encoding="utf-8")
    (fixture / "LICENSE").write_text("MIT", encoding="utf-8")
    (fixture / "NOTICE").write_text("Synthetic fixture", encoding="utf-8")
    (fixture / "pyproject.toml").write_text(
        '[project]\nname = "jev-filter"\nversion = "0.9.8"\nlicense = "MIT"\n',
        encoding="utf-8",
    )
    (fixture / "benchmarks/research/synthetic.html").write_text(
        "<html><body>Synthetic replay fixture</body></html>", encoding="utf-8"
    )
    for slug in SLUGS:
        for suffix in ("", ".zh-CN"):
            title = f"Guide {slug}{suffix}"
            paragraph = f"Learn {slug}{suffix} using portable synthetic evidence."
            (fixture / f"docs/{slug}{suffix}.md").write_text(
                f"# {title}\n\n{paragraph}\n", encoding="utf-8"
            )
    (fixture / "docs/index.md").write_text(
        '# Jev Filter overview\n\n<p><img src="assets/hero.svg" alt="Signal"></p>\n\n'
        "<p><img src='assets/hero.svg' alt='Signal with single quotes'></p>\n\n"
        "Filter retrieved evidence into typed decisions.\n\n"
        "[Start](getting-started.md#guide-getting-started) · "
        "[中文](index.zh-CN.md)\n",
        encoding="utf-8",
    )
    (fixture / "docs/index.zh-CN.md").write_text(
        "# Jev Filter 文档首页\n\n筛选检索证据，保留原文。\n\n"
        "[快速开始](getting-started.zh-CN.md) · [English](index.md)\n",
        encoding="utf-8",
    )
    (fixture / "docs/search-result-filtering.md").write_text(
        '# Filter "retrieved" records & evidence\n\n'
        'Keep **quoted** "records" & their evidence, with `stable IDs`.\n',
        encoding="utf-8",
    )
    for suffix, purpose in (
        ("", "Jev Filter screens retrieved evidence and keeps originals recoverable."),
        (".zh-CN", "Jev Filter 筛选检索证据，并保留可回查原文。"),
    ):
        (fixture / f"README{suffix}.md").write_text(
            '<p align="center"><a href="docs/getting-started.md">Quick start</a> · '
            '<a href="docs/faq.md">Documentation</a> · '
            '<a href="docs/agent-quickstart.md">Agent setup</a></p>\n\n'
            "```sh\n# A fenced shell comment is not the page title\n```\n\n"
            "# Jev Filter: **semantic evidence**\n\n"
            f"{purpose}\n\n",
            encoding="utf-8",
        )
    proofs = fixture / "docs/site-verification"
    proofs.mkdir()
    # Ownership proofs are byte-preserved artifacts, not documentation to parse.
    (proofs / "google-synthetic.html").write_bytes(
        b'google-site-verification: synthetic\r\n<a href="unavailable.txt">proof</a>\r\n'
    )
    subprocess.run(
        [sys.executable, str(fixture / "scripts/build_docs.py")], check=True, capture_output=True
    )
    return fixture


def test_homepages_render_maintained_content_and_rebased_links(built_site):
    site = built_site / "site"
    source = (site / "index.html").read_text(encoding="utf-8")
    assert "Filter retrieved evidence into typed decisions." in source
    assert "http-equiv" not in source
    page = ParsedPage(source)
    targets = {fields.get("href", fields.get("src")) for _, fields in page.links}
    assert "docs/assets/hero.svg" in targets
    assert "docs/getting-started.html#guide-getting-started" in targets
    assert "index.zh-CN.html" in targets
    assert "./" in targets
    assert "index.html" not in targets
    assert "style.css" in targets
    assert "sitemap.xml" in targets
    for slug in ("search-result-filtering", "semantic-code-search", "log-triage", "faq"):
        assert f"docs/{slug}.html" in targets
    chinese = (site / "index.zh-CN.html").read_text(encoding="utf-8")
    assert "筛选检索证据，保留原文。" in chinese
    assert 'lang="zh-CN"' in chinese
    guide = ParsedPage((site / "docs/faq.html").read_text(encoding="utf-8"))
    guide_targets = {fields.get("href") for _, fields in guide.links}
    assert "../" in guide_targets
    assert "../index.html" not in guide_targets
    check = subprocess.run(
        [sys.executable, str(built_site / "scripts/check_docs.py")], capture_output=True, text=True
    )
    assert check.returncode == 0, check.stdout + check.stderr


def test_canonical_home_aliases_and_language_alternates(built_site):
    for name, canonical in (
        ("index.html", BASE),
        ("docs/index.html", BASE),
        ("index.zh-CN.html", BASE + "index.zh-CN.html"),
        ("docs/index.zh-CN.html", BASE + "index.zh-CN.html"),
        ("docs/search-result-filtering.html", BASE + "docs/search-result-filtering.html"),
    ):
        page = ParsedPage((built_site / "site" / name).read_text(encoding="utf-8"))
        assert [f["href"] for tag, f in page.links if f.get("rel") == "canonical"] == [canonical]
        assert page.meta["og:url"] == canonical
        alternates = {f["hreflang"]: f["href"] for _, f in page.links if "hreflang" in f}
        if "index" in name:
            assert alternates == {"en": BASE, "zh-CN": BASE + "index.zh-CN.html", "x-default": BASE}
        else:
            assert alternates["en"] == canonical
            assert alternates["zh-CN"] == BASE + "docs/search-result-filtering.zh-CN.html"


def test_page_descriptions_are_accurate_distinct_and_escaped(built_site):
    site = built_site / "site"
    text = (site / "docs/search-result-filtering.html").read_text(encoding="utf-8")
    page = ParsedPage(text)
    expected = 'Keep quoted "records" & their evidence, with stable IDs.'
    assert page.meta["description"] == expected
    assert page.meta["og:description"] == expected
    assert 'content="Keep quoted &quot;records&quot; &amp; their evidence' in text
    other = ParsedPage((site / "docs/log-triage.html").read_text(encoding="utf-8"))
    assert other.meta["description"] != expected
    assert "log-triage" in other.meta["description"]
    home = ParsedPage((site / "index.html").read_text(encoding="utf-8"))
    code = next(s for s in home.scripts if s.get("@type") == "SoftwareSourceCode")
    assert code["codeRepository"] == "https://github.com/apixly-ai/jev-filter"
    assert code["license"] == "https://opensource.org/license/mit/"
    assert code["version"] == "0.9.8"
    assert "aggregateRating" not in code


def test_sitemap_contains_canonical_documents_without_aliases_or_research(built_site):
    site = built_site / "site"
    xml = ElementTree.parse(site / "sitemap.xml")
    locations = [
        node.text for node in xml.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
    ]
    assert len(locations) == len(set(locations))
    assert BASE in locations
    assert BASE + "index.zh-CN.html" in locations
    assert BASE + "docs/faq.html" in locations
    assert BASE + "docs/index.html" not in locations
    assert BASE + "docs/index.zh-CN.html" not in locations
    assert all("benchmarks/research" not in location for location in locations)
    assert not (site / "robots.txt").exists()
    assert (site / ("a" * 32 + ".txt")).read_text(encoding="utf-8") == "a" * 32


def test_checker_rejects_missing_generated_page_canonical(built_site):
    path = built_site / "site/docs/faq.html"
    text = path.read_text(encoding="utf-8")
    path.write_text(re.sub(r'<link rel="canonical"[^>]+>', "", text), encoding="utf-8")
    checked = subprocess.run(
        [sys.executable, str(built_site / "scripts/check_docs.py")], capture_output=True, text=True
    )
    assert checked.returncode != 0
    assert "canonical" in checked.stderr


def test_checker_checks_anchors_on_canonical_directory_home_links(built_site):
    path = built_site / "site/docs/faq.html"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace("</article>", '<a href="../#missing-home-section">Home</a></article>'),
        encoding="utf-8",
    )
    checked = subprocess.run(
        [sys.executable, str(built_site / "scripts/check_docs.py")], capture_output=True, text=True
    )
    assert checked.returncode != 0
    assert "missing anchor ../#missing-home-section" in checked.stderr


@pytest.mark.parametrize(
    ("filename", "purpose"),
    (
        ("README.html", "Jev Filter screens retrieved evidence and keeps originals recoverable."),
        ("README.zh-CN.html", "Jev Filter 筛选检索证据，并保留可回查原文。"),
    ),
)
def test_readme_title_uses_rendered_heading(built_site, filename, purpose):
    page = ParsedPage((built_site / "site" / filename).read_text(encoding="utf-8"))
    assert page.title == "Jev Filter: semantic evidence · Jev Filter"
    assert page.meta["og:title"] == page.title


@pytest.mark.parametrize(
    ("filename", "purpose"),
    (
        ("README.html", "Jev Filter screens retrieved evidence and keeps originals recoverable."),
        ("README.zh-CN.html", "Jev Filter 筛选检索证据，并保留可回查原文。"),
    ),
)
def test_readme_description_uses_introductory_prose(built_site, filename, purpose):
    page = ParsedPage((built_site / "site" / filename).read_text(encoding="utf-8"))
    assert page.meta["description"] == purpose
    assert page.meta["og:description"] == purpose


def test_guide_description_skips_single_reference_link(built_site):
    source = built_site / "docs/agent-quickstart.md"
    purpose = "Jev Filter returns typed evidence while keeping original records recoverable."
    source.write_text(
        "# Agent quickstart\n\n[简体中文](agent-quickstart.zh-CN.md)\n\n"
        "[Full integration reference](agents.md)\n\n" + purpose + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(built_site / "scripts/build_docs.py")], check=True, capture_output=True
    )
    page = ParsedPage((built_site / "site/docs/agent-quickstart.html").read_text(encoding="utf-8"))
    assert page.meta["description"] == purpose
    assert page.meta["og:description"] == purpose


def test_guide_description_keeps_prose_with_an_inline_link(built_site):
    source = built_site / "docs/agent-quickstart.md"
    source.write_text(
        "# Agent quickstart\n\n"
        "Review [recovered source evidence](recipes.md) before using a decision.\n",
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, str(built_site / "scripts/build_docs.py")], check=True, capture_output=True
    )
    page = ParsedPage((built_site / "site/docs/agent-quickstart.html").read_text(encoding="utf-8"))
    expected = "Review recovered source evidence before using a decision."
    assert page.meta["description"] == expected
    assert page.meta["og:description"] == expected


def test_site_verification_is_copied_as_uninterpreted_artifact(built_site):
    source = built_site / "docs/site-verification/google-synthetic.html"
    target = built_site / "site/google-synthetic.html"
    assert target.read_bytes() == source.read_bytes()
    assert BASE + target.name not in (built_site / "site/sitemap.xml").read_text(encoding="utf-8")
    checked = subprocess.run(
        [sys.executable, str(built_site / "scripts/check_docs.py")], capture_output=True, text=True
    )
    assert checked.returncode == 0, checked.stdout + checked.stderr
