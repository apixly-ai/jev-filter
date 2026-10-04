"""Hosted execution primitives on a real local Chromium over the stdlib CDP client."""

import functools
import http.server
import threading
from pathlib import Path

import pytest

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
    """The Playwright-managed Chromium (CI browser job); skipped elsewhere like test_browser.py."""
    sync = pytest.importorskip("playwright.sync_api")
    with sync.sync_playwright() as p:
        path = p.chromium.executable_path
    if not Path(path).is_file():
        pytest.skip("Playwright Chromium is not installed")
    return path


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
    assert state["password_fields"] == 1 and state["challenge"] is False
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


def synthetic(browser, body):
    browser.navigate("about:blank")
    import json

    browser.evaluate("document.body.innerHTML=" + json.dumps(body))


def test_native_and_aria_control_state_remains_verifiable(browser):
    synthetic(
        browser,
        '<label><input type="checkbox">Keep notifications</label>'
        '<button aria-label="Pin item" aria-pressed="false">Pin</button>'
        '<div role="tab" aria-selected="false">History</div>'
        '<label>Sort<select><option value="recent">Recent</option>'
        '<option value="old">Oldest</option></select></label>'
        '<input aria-label="Note" value="">',
    )
    state = browser.observe()
    assert by_label(state, "Keep notifications")["checked"] is False
    assert by_label(state, "Pin item")["pressed"] is False
    assert by_label(state, "History")["selected"] is False
    assert by_label(state, "Note", "fill")["value"] == ""
    select = by_label(state, "Sort", "click")
    assert select["control_value"] == "recent"
    option = by_label(state, "Sort → Oldest", "select")
    assert select["node"] == option["node"]
    assert option["control_label"] == "Sort"


def test_native_select_click_can_load_choices_through_observed_handler(browser):
    synthetic(
        browser,
        '<label>Lazy choices<select onclick="if(this.options.length===1){'
        "this.add(new Option('Loaded choice','loaded'));"
        "document.getElementById('out').textContent='Choices loaded';}"
        '">'
        '<option value="">Open picker</option></select></label><p id="out"></p>',
    )
    state = browser.observe()
    assert not any(a["kind"] == "select" for a in state["actions"])
    browser.act(by_label(state, "Lazy choices", "click"), state)
    assert browser.evaluate("document.getElementById('out').textContent") == "Choices loaded"
    assert by_label(browser.observe(), "Lazy choices → Loaded choice", "select")


def test_nested_scroll_exposes_remaining_travel_and_marks_clipped_controls(browser):
    from jev_context.act import space

    synthetic(
        browser,
        '<section aria-label="Results panel" style="overflow-y:auto;height:120px;width:400px">'
        '<div style="height:450px">Earlier results</div>'
        "<button>Load target</button></section>",
    )
    state = browser.observe()
    down = next(a for a in state["actions"] if a["kind"] == "scroll" and a.get("node"))
    assert down["scroll_top"] == 0
    assert down["client_height"] == 120
    assert down["scroll_height"] > 450
    assert down["scroll_max"] == down["scroll_height"] - down["client_height"]
    assert down["remaining_down"] == down["scroll_max"]
    assert down["container"] == "Results panel"
    assert state["clipped_actions"] == 1 and state["covered_actions"] == 0
    assert "Load target" not in state["text"]
    clipped = state["clipped_controls"][0]
    assert clipped["label"] == "Load target" and clipped["direction"] == "down"
    assert clipped["container_node"] == down["node"]
    body, _, _ = space.build_request(state, "Load the needed item", [])
    operation = body["questions"]["operation"]["criteria"][down["id"].upper()]
    assert operation["scroll_top"] == 0 and operation["remaining_down"] == down["scroll_max"]
    assert body["state"]["notes"]["clipped_controls"] == state["clipped_controls"]
    browser.act(down, state)
    later = browser.observe()
    current = next(a for a in later["actions"] if a["kind"] == "scroll" and a.get("delta", 0) > 0)
    assert current["scroll_top"] > 0 and current["remaining_down"] < down["remaining_down"]


def test_roleless_clickable_and_transparent_native_toggle(browser):
    synthetic(
        browser,
        '<div tabindex="0" style="cursor:pointer;width:150px;height:30px"'
        " onclick=\"this.textContent='Opened'\">Open details</div>"
        '<label style="display:block;width:220px;height:30px">'
        '<input type="checkbox" style="opacity:0;width:15px;height:15px">Styled toggle</label>',
    )
    state = browser.observe()
    browser.act(by_label(state, "Open details"), state)
    state = browser.observe()
    assert "Opened" in state["text"]
    toggle = by_label(state, "Styled toggle")
    assert toggle["checked"] is False
    browser.act(toggle, state)
    assert by_label(browser.observe(), "Styled toggle")["checked"] is True


def test_nested_scroll_is_enumerated_and_guarded(browser):
    synthetic(
        browser,
        '<section aria-label="Results panel" style="overflow-y:auto;height:120px;width:400px">'
        '<div style="height:500px">Earlier results</div><button>Load target</button></section>',
    )
    state = browser.observe()
    scroll = next(a for a in state["actions"] if a["kind"] == "scroll" and a.get("node"))
    assert "Results panel" in scroll["label"]
    assert by_label(state, "Wait for the page to update")["kind"] == "wait"
    record = browser.act(scroll, state)
    assert record["scrolled"]
    assert not browser.fresh(state, scroll)
    for _ in range(8):
        state = browser.observe()
        target = next((a for a in state["actions"] if a["label"] == "Load target"), None)
        if target:
            browser.act(target, state)
            break
        scroll = next(
            a
            for a in state["actions"]
            if a["kind"] == "scroll" and a.get("node") and a["delta"] > 0
        )
        browser.act(scroll, state)
    else:
        pytest.fail("nested scrolling never revealed the target")


def test_transparent_toggle_surface_must_be_in_the_observed_scope(browser):
    synthetic(
        browser,
        '<main id="scope"><input id="toggle" type="checkbox" style="opacity:0"></main>'
        '<label for="toggle">Outside toggle</label>',
    )
    state = browser.observe(scope="#scope")
    assert all(a.get("control_label") != "Outside toggle" for a in state["actions"])


def test_sensitive_native_select_does_not_expose_option_values(browser):
    synthetic(
        browser,
        '<label>Verification code<select autocomplete="one-time-code">'
        '<option value="PRIVATE_OTP_CURRENT">Provided code</option>'
        '<option value="PRIVATE_OTP_ALTERNATIVE">Alternate code</option></select></label>',
    )
    state = browser.observe()
    assert "PRIVATE_OTP" not in str(state)
    assert all(a.get("control_label") != "Verification code" for a in state["actions"])
