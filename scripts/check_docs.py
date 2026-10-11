"""Verify local documentation links and canonical search-discovery metadata."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1] / "site"
SITE_URL = "https://apixly-ai.github.io/jev-filter/"
GENERATOR = "Jev Filter documentation"


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.meta = {}
        self.canonicals = []
        self.alternates = {}

    def handle_starttag(self, tag, attrs):
        fields = dict(attrs)
        if fields.get("id"):
            self.ids.add(fields["id"])
        for key in ("href", "src"):
            if fields.get(key):
                self.links.append(fields[key])
        if tag == "meta":
            self.meta[fields.get("name", fields.get("property"))] = fields.get("content")
        if tag == "link" and fields.get("rel") == "canonical":
            self.canonicals.append(fields.get("href", ""))
        if tag == "link" and fields.get("rel") == "alternate" and "hreflang" in fields:
            self.alternates[fields["hreflang"]] = fields.get("href", "")


def canonical_destination(url, root):
    if not url.startswith(SITE_URL):
        return None
    # Canonical discovery URLs must not encode a second URL, query or fragment.
    parts = urlsplit(url)
    if parts.query or parts.fragment:
        return None
    relative = unquote(parts.path[len(urlsplit(SITE_URL).path) :])
    destination = (root / (relative or "index.html")).resolve()
    return destination if destination.is_relative_to(root.resolve()) else None


def check(root=ROOT):
    root = root.resolve()
    verification = root.parent / "docs/site-verification"
    ownership_artifacts = (
        {root / proof.name for proof in verification.iterdir() if proof.is_file()}
        if verification.exists()
        else set()
    )
    pages = {}
    for path in root.rglob("*.html"):
        if path in ownership_artifacts:
            continue
        parser = Page()
        parser.feed(path.read_text(encoding="utf-8"))
        pages[path.resolve()] = parser
    if not pages:
        return ["No built documentation pages found"], 0
    errors = []
    generated = {
        path: page for path, page in pages.items() if page.meta.get("generator") == GENERATOR
    }
    canonical_urls = set()
    for path, page in pages.items():
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            if url.path.startswith("/"):
                base = urlsplit(SITE_URL).path
                destination = (
                    (root / unquote(url.path[len(base) :])).resolve()
                    if url.path.startswith(base)
                    else root / "__outside_project_site__"
                )
            else:
                destination = (path.parent / unquote(url.path)).resolve() if url.path else path
            if destination.is_dir() and (destination / "index.html").exists():
                destination = destination / "index.html"
            if not destination.exists():
                errors.append(f"{path.relative_to(root)}: missing {link}")
            elif (
                url.fragment
                and destination in pages
                and unquote(url.fragment) not in pages[destination].ids
            ):
                errors.append(f"{path.relative_to(root)}: missing anchor {link}")
        if path not in generated:
            continue
        label = path.relative_to(root)
        if len(page.canonicals) != 1:
            errors.append(f"{label}: expected one absolute canonical URL")
            continue
        canonical = page.canonicals[0]
        destination = canonical_destination(canonical, root)
        if destination not in generated:
            errors.append(f"{label}: canonical URL is outside generated documentation: {canonical}")
        elif generated[destination].canonicals != [canonical]:
            errors.append(f"{label}: canonical target does not agree: {canonical}")
        canonical_urls.add(canonical)
        if page.meta.get("og:url") != canonical:
            errors.append(f"{label}: og:url must match canonical URL")
        if not page.meta.get("description") or not page.meta.get("og:description"):
            errors.append(f"{label}: missing page description")
        for language, alternate in page.alternates.items():
            other = canonical_destination(alternate, root)
            if other not in generated or generated[other].canonicals != [alternate]:
                errors.append(f"{label}: invalid {language} language alternate: {alternate}")
            elif language != "x-default" and canonical not in generated[other].alternates.values():
                errors.append(f"{label}: {language} language alternate lacks reciprocal link")
    try:
        sitemap = ElementTree.parse(root / "sitemap.xml")
        namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
        locations = [n.text for n in sitemap.findall(f".//{{{namespace}}}loc")]
        if len(locations) != len(set(locations)):
            errors.append("sitemap.xml: duplicate canonical URLs")
        if set(locations) != canonical_urls:
            errors.append("sitemap.xml: URLs must match generated canonical documentation")
    except (OSError, ElementTree.ParseError) as exc:
        errors.append(f"sitemap.xml: {exc}")
    try:
        text_locations = (root / "sitemap.txt").read_text(encoding="utf-8").splitlines()
        if text_locations != sorted(canonical_urls):
            errors.append("sitemap.txt: URLs must match sorted unique canonical documentation")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"sitemap.txt: {exc}")
    return errors, len(pages)


if __name__ == "__main__":
    errors, count = check()
    if errors:
        raise SystemExit("\n".join(errors))
    print(
        f"Checked {count} documentation pages: links, images, anchors and discovery metadata passed."
    )
