"""Publish notifications stay inside a verified documentation prefix, without retries."""

import importlib.util
import json
from pathlib import Path
from urllib.error import URLError

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/submit_indexnow.py"
spec = importlib.util.spec_from_file_location("submit_indexnow", SCRIPT)
notifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notifier)
KEY = "0123456789abcdef0123456789abcdef"
BASE = "https://example.com/jev-filter/"


def payload(tmp_path, urls=None):
    sitemap = tmp_path / "sitemap.xml"
    urls = urls or [BASE, BASE + "docs/faq.html"]
    sitemap.write_text(
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
        + "".join(f"<url><loc>{url}</loc></url>" for url in urls)
        + "</urlset>",
        encoding="utf-8",
    )
    key = tmp_path / "key.txt"
    key.write_text(KEY + "\n", encoding="utf-8")
    return notifier.make_payload(sitemap, key, BASE)


def test_project_key_location_and_deduplicated_payload(tmp_path):
    data = payload(tmp_path, [BASE, BASE, BASE + "docs/faq.html"])
    assert data["host"] == "example.com"
    assert data["keyLocation"] == BASE + KEY + ".txt"
    assert data["urlList"] == [BASE, BASE + "docs/faq.html"]


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/other/",
        "https://other.example/jev-filter/",
        "http://example.com/jev-filter/",
        BASE + "../other/",
        BASE + "%2e%2e/other/",
        BASE + "docs/faq.html#answer",
    ],
)
def test_out_of_scope_urls_are_rejected_before_network(tmp_path, url):
    with pytest.raises(ValueError, match="scope"):
        payload(tmp_path, [url])


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_live_key_mismatch_prevents_notification(tmp_path):
    calls = []

    def open_url(request, **kwargs):
        calls.append(request)
        return Response(b"wrong-key")

    with pytest.raises(ValueError, match="verification key"):
        notifier.submit_payload(payload(tmp_path), opener=open_url)
    assert len(calls) == 1
    assert calls[0].get_method() == "GET"


def test_accepted_notification_does_not_claim_indexing(tmp_path):
    calls = []

    def open_url(request, **kwargs):
        calls.append(request)
        return Response(KEY.encode()) if len(calls) == 1 else Response(b"", 202)

    result = notifier.submit_payload(payload(tmp_path), opener=open_url)
    assert len(calls) == 2
    assert json.loads(calls[1].data)["key"] == KEY
    assert result == {
        "status": "received_key_validation_pending",
        "http_status": 202,
        "submitted_urls": 2,
        "indexing_verified": False,
    }


def test_uncertain_post_is_not_retried(tmp_path):
    calls = []

    def open_url(request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            return Response(KEY.encode())
        raise URLError("connection lost after write")

    with pytest.raises(URLError):
        notifier.submit_payload(payload(tmp_path), opener=open_url)
    assert len(calls) == 2
