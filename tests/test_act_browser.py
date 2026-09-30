"""Hosted execution primitives on a real local Chromium over the stdlib CDP client."""

import functools
import http.server
import threading
from pathlib import Path

import pytest

from jev_context.act import cdp
from jev_context.act.browser import CDPPage, StalePage

SITE = Path(__file__).resolve().parents[1] / "benchmarks" / "sites" / "shop"
pytestmark = pytest.mark.browser


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def origin():
    server = http.server.ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(Quiet, directory=str(SITE))
    )
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def executable():
    try:
        sync = pytest.importorskip("playwright.sync_api")
        with sync.sync_playwright() as p:
            path = p.chromium.executable_path
        if Path(path).is_file():
            return path
    except Exception:
        pass
    try:
        return cdp.find_chromium()
    except cdp.CDPError:
        pytest.skip("no Chromium available")


@pytest.fixture
def browser(executable):
    page = CDPPage(executable=executable)
    yield page
    page.close()


def by_label(state, label, kind=None):
    return next(
        a for a in state["actions"] if a["label"] == label and (kind is None or a["kind"] == kind)
    )


def test_modal_consent_covers_page_until_dismissed(browser, origin):
    browser.navigate(origin + "/index.html")
    state = browser.observe()
    labels = {a["label"] for a in state["actions"] if "node" in a}
    assert labels == {"Reject optional cookies", "Accept all cookies"}
    assert state["covered_actions"] > 0 and "Cookie consent" in state["dialogs"]
    browser.act(by_label(state, "Reject optional cookies"), state)
    browser.settle({})
    state = browser.observe()
    kinds = {(a["label"], a["kind"]) for a in state["actions"]}
    assert ("Search products", "fill") in kinds and ("Search", "click") in kinds
    assert ("Category → Shoes", "select") in kinds and ("In stock only", "click") in kinds
    assert not state["dialogs"]


def test_fill_waits_for_autocomplete_and_select_applies(browser, origin):
    browser.navigate(origin + "/index.html")
    browser.evaluate("localStorage.setItem('consent','reject')")
    browser.navigate(origin + "/index.html")
    state = browser.observe()
    field = by_label(state, "Search products", "fill")
    record = browser.act(field, state, text="red shoes")
    assert not record.get("readback_mismatch")
    browser.settle(field)
    state = browser.observe()
    assert any(a["role"] == "option" and a["label"] == "red shoes" for a in state["actions"])
    assert by_label(state, "Search products", "fill")["value"] == "red shoes"
    option = by_label(state, "Category → Shoes")
    browser.act(option, state)
    state = browser.observe()
    assert by_label(state, "Category → Jackets")["current_value"] == "Shoes"


def test_sensitive_fields_never_leave_the_page(browser, origin):
    browser.navigate(origin + "/account.html")
    state = browser.observe()
    labels = [a["label"] for a in state["actions"]]
    assert "Password" not in labels
    otp = by_label(state, "One-time code", "fill")
    assert otp["sensitive"] is True
    browser.act(otp, state, text="123456")
    state = browser.observe()
    assert by_label(state, "One-time code", "fill")["value"] == "[filled]"
    assert "123456" not in str(state)


def test_shadow_dom_and_same_origin_frame_are_actionable(browser, origin):
    browser.navigate(origin + "/widgets.html")
    state = browser.observe()
    shadow = by_label(state, "Shadow action")
    framed = by_label(state, "Framed action")
    assert framed.get("frame") is True and state["frames"]["same_origin"] == 1
    browser.act(shadow, state)
    assert "Shadow action done." in browser.observe()["text"]
    state = browser.observe()
    browser.act(by_label(state, "Framed action"), state)
    assert "Framed action done." in browser.observe()["text"]


def test_javascript_dialog_is_dismissed_without_hanging(browser, origin):
    browser.navigate(origin + "/widgets.html")
    state = browser.observe()
    browser.act(by_label(state, "Archive notes"), state)
    browser.settle({})
    assert "Archive cancelled." in browser.observe()["text"]
    assert browser.dialogs and browser.dialogs[0]["type"] == "confirm"


def test_guard_rejects_changed_or_covered_targets(browser, origin):
    browser.navigate(origin + "/widgets.html")
    state = browser.observe()
    target = by_label(state, "Archive notes")
    browser.evaluate("document.getElementById('confirm-btn').textContent='Delete notes'")
    assert not browser.fresh(state, target)
    with pytest.raises(StalePage):
        browser.act(target, state)
    state = browser.observe()
    target = by_label(state, "Delete notes")
    browser.evaluate(
        "(() => { const d = document.createElement('div');"
        " d.style.cssText='position:fixed;inset:0;z-index:9;background:transparent';"
        " document.body.appendChild(d); })()"
    )
    with pytest.raises(StalePage, match="covered"):
        browser.resolve(target)


def test_extract_turns_tables_into_header_labelled_rows(browser, origin):
    browser.navigate(origin + "/results.html?q=red+shoes&cat=shoes")
    data = browser.extract()
    rows = [r["text"] for r in data["records"] if r["kind"] == "row"]
    assert rows[0].startswith("Product: Red Runner | Category: shoes | Price: $59")
    assert len(rows) == 3
    assert any(
        r["kind"] == "link" and r["href"].endswith("product.html?id=1") for r in data["records"]
    )


def test_long_form_reports_content_below_the_fold(browser, origin):
    browser.navigate(origin + "/form.html")
    state = browser.observe()
    assert state["below_fold"] > 0
    scroll = next(a for a in state["actions"] if a["id"] == "scroll_down")
    browser.act(scroll, state)
    browser.settle(scroll)
    later = browser.observe()
    assert any(a["label"].startswith("Topic") for a in later["actions"])
