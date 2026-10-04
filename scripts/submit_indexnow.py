"""Notify IndexNow of deployed public docs; receipt never establishes search indexing."""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen

SITE_URL = "https://apixly-ai.github.io/jev-filter/"
ENDPOINT = "https://api.indexnow.org/indexnow"
ROOT = Path(__file__).resolve().parents[1]


def make_payload(sitemap, key_file, site_url=SITE_URL):
    """Admit canonical sitemap URLs only within the public verification key's directory."""
    key = Path(key_file).read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"[a-f0-9]{32}", key):
        raise ValueError("Invalid public IndexNow verification key")
    base = urlsplit(site_url)
    if base.scheme != "https" or not base.netloc or not base.path.endswith("/"):
        raise ValueError("Invalid site scope")
    if base.username or base.password or base.query or base.fragment:
        raise ValueError("Invalid site scope")
    urls = sorted(
        {
            node.text.strip()
            for node in ET.parse(sitemap).findall("{*}url/{*}loc")
            if node.text and node.text.strip()
        }
    )
    if not urls or len(urls) > 10000:
        raise ValueError("Sitemap must contain 1–10000 URLs")
    for url in urls:
        parsed = urlsplit(url)
        path = unquote(parsed.path)
        if (
            parsed.scheme != base.scheme
            or parsed.netloc != base.netloc
            or not path.startswith(base.path)
            or any(part in (".", "..") for part in path.split("/"))
            or "\\" in path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Sitemap URL outside verified project scope")
    return {
        "host": base.netloc,
        "key": key,
        "keyLocation": site_url + key + ".txt",
        "urlList": urls,
    }


def submit_payload(payload, *, opener=urlopen):
    """Verify deployed proof, then send once; uncertain notifications are not retried."""
    proof = Request(payload["keyLocation"], headers={"User-Agent": "jev-filter-docs/1.0"})
    with opener(proof, timeout=20) as response:
        if response.status != 200 or response.read().decode("utf-8").strip() != payload["key"]:
            raise ValueError("Deployed verification key does not match")
    request = Request(
        ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with opener(request, timeout=20) as response:
        status = response.status
    if status not in (200, 202):
        raise RuntimeError(f"IndexNow notification failed with HTTP {status}")
    return {
        "status": "received" if status == 200 else "received_key_validation_pending",
        "http_status": status,
        "submitted_urls": len(payload["urlList"]),
        "indexing_verified": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sitemap", type=Path, default=ROOT / "site/sitemap.xml")
    parser.add_argument("--key-file", type=Path, default=ROOT / "scripts/indexnow-key.txt")
    parser.add_argument("--submit", action="store_true", help="Verify live key and notify once")
    args = parser.parse_args(argv)
    payload = make_payload(args.sitemap, args.key_file)
    if args.submit:
        result = submit_payload(payload)
    else:
        result = {"status": "offline_preview", "payload": payload, "indexing_verified": False}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
