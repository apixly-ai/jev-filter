"""Hosted desktop execution: generic surface, macOS AX logic on a fake tree, live Windows UIA/OCR."""

import subprocess
import sys
import time
from pathlib import Path

import pytest

from jev_context.act import kernel
from jev_context.act.browser import StalePage
from jev_context.act.desktop import DesktopSurface
from jev_context.act.desktop_macos import MacBackend

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "benchmarks" / "sites" / "desktop"


# ---------------------------------------------------------------------------------------------
# Generic surface over a scripted backend
# ---------------------------------------------------------------------------------------------
class Ctl:
    def __init__(self, role, label, kinds, **state):
        self.role, self.label, self.kinds, self.state = role, label, kinds, dict(state)
        self.alive = True


class FakeBackend:
    class Gone(RuntimeError):
        pass

    def __init__(self, controls, status="Status: idle"):
        self.controls_ = controls
        self.status = status
        self.performed = []
        self.closed = False

    def window_info(self):
        return {
            "title": "Fixture",
            "pid": 1,
            "process": "fixture.exe",
            "rect": [0, 0, 400, 300],
            "focus": None,
            "dialogs": [],
        }

    def describe(self, c, section="", owner=None):
        if not c.alive:
            return None
        return {
            "role": c.role,
            "label": c.label,
            "section": section,
            "rect": [1, 1, 5, 5],
            "enabled": True,
            "kinds": list(c.kinds),
            **c.state,
        }

    def snapshot(self, limit=400):
        elements = []
        for i, c in enumerate(self.controls_):
            info = self.describe(c, "Profile")
            if info:
                info.update(node=f"n{i}", handle=c)
                elements.append(info)
        return elements, ["Fixture", self.status]

    def controls(self, window):
        return [{"id": "press_escape", "kind": "key", "key": "Escape", "label": "Press Escape"}]

    def perform(self, c, kind, text=None):
        self.performed.append((c.label, kind, text))
        if kind == "fill":
            c.state["value"] = text
        elif c.role == "checkbox":
            c.state["checked"] = not c.state.get("checked", False)
        elif c.label == "Save profile":
            name = next(x for x in self.controls_ if x.label == "Customer name").state.get("value")
            self.status = f"Status: saved {name}"
        return {"via": "fake"}

    def control(self, action):
        self.performed.append((action["id"], "key", None))
        return {"via": "keyboard"}

    def close(self):
        self.closed = True


def controls():
    return [
        Ctl("textbox", "Customer name", ["fill", "click"], value=""),
        Ctl("textbox", "PIN code", ["fill"], value="1234", sensitive=True),
        Ctl("checkbox", "Send weekly report", ["click"], checked=False),
        Ctl("option", "Pro", ["select"], owner="Plan", owner_value="Free"),
        Ctl("button", "Save profile", ["click"]),
        Ctl("button", "Delete all records", ["click"]),
    ]


def test_surface_shapes_actions_like_a_browser_page():
    surface = DesktopSurface(FakeBackend(controls()))
    state = surface.observe()
    kinds = [(a["kind"], a["label"]) for a in state["actions"]]
    assert ("fill", "Customer name") in kinds and ("click", "Focus Customer name") in kinds
    assert ("select", "Plan → Pro") in kinds
    pin = next(a for a in state["actions"] if a["label"] == "PIN code")
    assert pin["value"] == "[filled]" and pin["sensitive"] is True and "1234" not in str(state)
    assert state["url"] == "window://fixture.exe/Fixture" and state["fingerprint"]
    assert state["actions"][-1]["id"] == "wait"


def test_surface_rejects_changed_or_vanished_elements():
    backend = FakeBackend(controls())
    surface = DesktopSurface(backend)
    state = surface.observe()
    save = next(a for a in state["actions"] if a["label"] == "Save profile")
    assert surface.fresh(state, save)
    backend.controls_[4].label = "Save and close"
    assert not surface.fresh(state, save)
    with pytest.raises(StalePage):
        surface.act(save, state)
    backend.controls_[4].alive = False
    assert not surface.fresh(state, save)


def test_ocr_fallback_only_when_accessibility_is_too_thin():
    class FakeOCR:
        def __init__(self):
            self.calls = 0

        def lines(self, window):
            self.calls += 1
            return [{"text": "Start game", "rect": [10, 10, 90, 30]}]

    ocr = FakeOCR()
    rich = DesktopSurface(FakeBackend(controls()), ocr=ocr, ocr_min_actions=2)
    rich.observe()
    assert ocr.calls == 0
    thin = DesktopSurface(FakeBackend([]), ocr=ocr, ocr_min_actions=2)
    state = thin.observe()
    assert ocr.calls == 1
    target = next(a for a in state["actions"] if a.get("source") == "ocr")
    assert target["label"] == "Start game" and target["kind"] == "click"


def choice(options, selected):
    return {
        "type": "choice",
        "choice": selected,
        "confidence": 0.9,
        "probabilities": {o: float(o == selected) for o in options},
    }


def scripted(script):
    def decide(body):
        op, label = (script.pop(0) + (None,))[:2]
        qs = body["questions"]
        answers = {"operation": choice(qs["operation"]["criteria"], op)}
        for name, q in qs.items():
            if name.endswith("_target"):
                pick = next(
                    (
                        k
                        for k, v in q["criteria"].items()
                        if label and v["element"].endswith("] " + label)
                    ),
                    next(iter(q["criteria"])),
                )
                answers[name] = choice(q["criteria"], pick)
            elif name == "type_value":
                answers[name] = choice(q["criteria"], "name")
            elif name == "irreversible":
                answers[name] = {"type": "noul", "noul": 0.05}
        return {
            "answers": answers,
            "usage": {"input_tokens": 10, "output_tokens": 1},
            "usage_complete": True,
        }

    return decide


def test_kernel_runs_a_desktop_goal_and_gates_destructive_buttons():
    backend = FakeBackend(controls())
    surface = DesktopSurface(backend, settle_s=0)
    decide = scripted(
        [
            ("TYPE_TEXT", "Customer name"),
            ("CLICK", "Send weekly report"),
            ("CLICK", "Save profile"),
            ("DONE",),
        ]
    )
    result = kernel.Run(
        surface, "Save Ada", decide=decide, values={"name": "Ada"}, verify_text="saved Ada"
    ).run()
    assert result["status"] == "done" and result["verification"]["passed"]
    assert backend.performed[0] == ("Customer name", "fill", "Ada")
    gated = kernel.Run(
        DesktopSurface(FakeBackend(controls()), settle_s=0),
        "Wipe",
        decide=scripted([("CLICK", "Delete all records")]),
    ).run()
    assert (
        gated["status"] == "needs_confirmation"
        and gated["pending"]["label"] == "Delete all records"
    )


# ---------------------------------------------------------------------------------------------
# macOS backend logic on a fake accessibility tree (runs on every platform)
# ---------------------------------------------------------------------------------------------
class AX:
    def __init__(
        self,
        role,
        title=None,
        value=None,
        children=(),
        rect=(10, 10, 110, 40),
        subrole=None,
        enabled=True,
        settable=False,
        actions=("AXPress",),
    ):
        self.attrs = {
            "AXRole": role,
            "AXTitle": title,
            "AXValue": value,
            "AXSubrole": subrole,
            "AXEnabled": enabled,
            "AXChildren": list(children),
            "AXPosition": ("pt", rect[0], rect[1]),
            "AXSize": ("sz", rect[2] - rect[0], rect[3] - rect[1]),
        }
        self.settable_ = settable
        self.actions_ = list(actions)
        self.performed = []


class FakeAXApi:
    def __init__(self, window, pid=42):
        self.window, self.pid = window, pid
        self.clicks, self.keys = [], []

    def trusted(self, prompt=False):
        return True

    def applications(self):
        yield {"pid": self.pid, "name": "Fixture"}

    def app(self, pid):
        return AX("AXApplication", children=[self.window])

    def get(self, element, attribute):
        if attribute == "AXWindows" and element.attrs["AXRole"] == "AXApplication":
            return [self.window]
        if attribute == "AXFocusedUIElement":
            return None
        return element.attrs.get(attribute)

    def point(self, value):
        return value[1], value[2]

    def size(self, value):
        return value[1], value[2]

    def actions(self, element):
        return element.actions_

    def perform(self, element, action):
        element.performed.append(action)
        return True

    def set(self, element, attribute, value):
        element.attrs[attribute] = value
        return True

    def settable(self, element, attribute):
        return element.settable_

    def pid_at(self, x, y):
        return self.pid

    def click(self, x, y):
        self.clicks.append((x, y))

    def key(self, pid, code):
        self.keys.append(code)

    def activate(self, pid):
        pass


def mac_tree():
    menu = AX(
        "AXMenu",
        children=[
            AX("AXMenuItem", "Free", actions=("AXPick",)),
            AX("AXMenuItem", "Pro", actions=("AXPick",)),
        ],
    )
    return AX(
        "AXWindow",
        "Jev Desktop Fixture",
        rect=(0, 0, 560, 420),
        children=[
            AX("AXTextField", "Customer name", value="", settable=True, actions=()),
            AX("AXTextField", "PIN", value="1234", subrole="AXSecureTextField", settable=True),
            AX(
                "AXPopUpButton",
                "Plan",
                value="Free",
                children=[menu],
                actions=("AXPress", "AXShowMenu"),
            ),
            AX("AXCheckBox", "Send weekly report", value=0),
            AX("AXGroup", "Danger zone", children=[AX("AXButton", "Delete all records")]),
            AX("AXButton", "Disabled", enabled=False),
            AX("AXButton", "Tiny", rect=(5, 5, 5, 5)),
            AX("AXStaticText", value="Status: idle"),
            AX("AXButton", "Custom", actions=()),
        ],
    )


def test_mac_backend_describes_ax_tree_without_secrets():
    api = FakeAXApi(mac_tree())
    surface = DesktopSurface(MacBackend(window="Jev", api=api), settle_s=0)
    state = surface.observe()
    labels = [(a["kind"], a["label"]) for a in state["actions"] if "node" in a]
    assert ("fill", "Customer name") in labels
    assert ("select", "Plan → Pro") in labels and ("click", "Open Plan") in labels
    assert ("click", "Send weekly report") in labels
    assert not any("PIN" in label or "Disabled" in label or "Tiny" in label for _, label in labels)
    delete = next(a for a in state["actions"] if a["label"] == "Delete all records")
    assert delete["section"] == "Danger zone"
    assert "Status: idle" in state["text"]


def test_mac_backend_executes_through_ax_actions_then_pointer():
    tree = mac_tree()
    api = FakeAXApi(tree)
    surface = DesktopSurface(MacBackend(window="Jev", api=api), settle_s=0)
    state = surface.observe()
    field = next(
        a for a in state["actions"] if a["label"] == "Customer name" and a["kind"] == "fill"
    )
    assert surface.act(field, state, text="Ada")["via"] == "value"
    assert tree.attrs["AXChildren"][0].attrs["AXValue"] == "Ada"
    state = surface.observe()
    pro = next(a for a in state["actions"] if a["label"] == "Plan → Pro")
    assert surface.act(pro, state)["via"] == "pick"
    state = surface.observe()
    custom = next(a for a in state["actions"] if a["label"] == "Custom")
    assert surface.act(custom, state)["via"] == "pointer" and api.clicks


def test_mac_backend_requires_accessibility_permission():
    api = FakeAXApi(mac_tree())
    api.trusted = lambda prompt=False: False
    with pytest.raises(RuntimeError, match="accessibility_permission_required"):
        MacBackend(window="Jev", api=api)


# ---------------------------------------------------------------------------------------------
# Live Windows UI Automation and OCR (opt-in marker, Windows only)
# ---------------------------------------------------------------------------------------------
windows = pytest.mark.skipif(sys.platform != "win32", reason="Windows UI Automation")


def launch(title, *command):
    process = subprocess.Popen(list(command) + [title])
    return process


@pytest.fixture
def winforms():
    pytest.importorskip("uiautomation")
    from jev_context.act.desktop_windows import WindowsBackend

    title = f"JevTest{time.monotonic_ns() % 10**8}"
    process = launch(
        title,
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(FIXTURE / "fixture.ps1"),
    )
    surface = DesktopSurface(WindowsBackend(window=f"^{title}$"))
    yield surface
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(process.pid)], capture_output=True)


def by(state, label, kind=None):
    return next(
        a for a in state["actions"] if a["label"] == label and (kind is None or a["kind"] == kind)
    )


@windows
@pytest.mark.desktop
def test_windows_uia_fixture_round_trip(winforms):
    s = winforms
    state = s.observe()
    labels = [a["label"] for a in state["actions"]]
    assert "PIN" not in labels and "关闭" not in labels and "Close" not in labels
    assert "Delete all records" in labels and "Advanced" in labels
    s.act(by(state, "Customer name", "fill"), state, text="Ada Lovelace")
    state = s.observe()
    s.act(by(state, "Open Plan"), state)
    s.settle({})
    state = s.observe()
    s.act(by(state, "Plan → Pro"), state)
    s.settle({})
    state = s.observe()
    s.act(by(state, "Send weekly report"), state)
    state = s.observe()
    s.act(by(state, "Save profile"), state)
    s.settle({})
    assert "Status: saved Ada Lovelace / Pro / weekly=True" in s.observe()["text"]


@windows
@pytest.mark.desktop
def test_windows_ocr_fallback_clicks_drawn_text():
    pytest.importorskip("uiautomation")
    pytest.importorskip("winrt.windows.media.ocr")
    from jev_context.act.desktop_windows import WindowsBackend
    from jev_context.act.ocr import open_ocr

    title = f"JevCanvas{time.monotonic_ns() % 10**8}"
    process = launch(title, sys.executable, str(FIXTURE / "canvas_app.py"))
    try:
        s = DesktopSurface(WindowsBackend(window=f"^{title}$"), ocr=open_ocr("on"))
        state = s.observe()
        target = next(
            a for a in state["actions"] if a.get("source") == "ocr" and a["label"] == "Settings"
        )
        s.act(target, state)
        time.sleep(0.4)
        assert "opened Settings" in s.observe()["text"]
    finally:
        process.kill()


# ---------------------------------------------------------------------------------------------
# Deterministic desktop safety gates
# ---------------------------------------------------------------------------------------------
def test_sensitive_targets_are_refused_unless_allowed():
    from jev_context.act import desktop_policy as policy

    with pytest.raises(policy.DesktopRefused, match="refused_sensitive_target"):
        policy.check_target("WindowsTerminal.exe")
    with pytest.raises(policy.DesktopRefused):
        policy.check_target("powershell.exe", "ConsoleWindowClass")
    policy.check_target(
        "powershell.exe", "WindowsForms10.Window.8.app"
    )  # a GUI app hosted by PowerShell
    policy.check_target("KeePassXC.exe", allow_sensitive=True)

    class Identified(FakeBackend):
        def identity(self):
            return {"pid": None, "process": "1Password.exe", "window_class": "x"}

    backend = Identified(controls())
    with pytest.raises(policy.DesktopRefused):
        DesktopSurface(backend)
    assert backend.closed


def test_stop_file_aborts_before_the_next_input(tmp_path, monkeypatch):
    from jev_context.act import desktop_policy as policy
    from jev_context.act.browser import ActionFailed

    stop = tmp_path / "STOP"
    monkeypatch.setenv("JEV_STOP_FILE", str(stop))
    monkeypatch.setattr(policy, "pointer_in_corner", lambda: False)
    monkeypatch.setattr(policy, "desktop_locked", lambda: False)
    surface = DesktopSurface(FakeBackend(controls()), settle_s=0)
    state = surface.observe()
    save = next(a for a in state["actions"] if a["label"] == "Save profile")
    stop.write_text("stop", encoding="utf-8")
    with pytest.raises(ActionFailed, match="stop file"):
        surface.act(save, state)
    stop.unlink()
    monkeypatch.setattr(policy, "pointer_in_corner", lambda: True)
    with pytest.raises(ActionFailed, match="corner"):
        surface.act(save, state)
    # A pointer already resting in the corner when the run starts does not trip the switch.
    resting = DesktopSurface(FakeBackend(controls()), settle_s=0)
    state = resting.observe()
    monkeypatch.setattr(policy, "desktop_locked", lambda: False)
    assert resting.act(next(a for a in state["actions"] if a["label"] == "Save profile"), state)
    monkeypatch.setattr(policy, "pointer_in_corner", lambda: False)
    monkeypatch.setattr(policy, "desktop_locked", lambda: True)
    with pytest.raises(ActionFailed, match="locked"):
        surface.act(save, state)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS Accessibility")
@pytest.mark.desktop
def test_macos_ax_fixture_round_trip():
    AS = pytest.importorskip("ApplicationServices")
    if not AS.AXIsProcessTrusted():
        pytest.skip("Accessibility is not granted to this Python")
    title = f"JevMac{time.monotonic_ns() % 10**8}"
    process = launch(title, sys.executable, str(FIXTURE / "fixture_mac.py"))
    try:
        s = DesktopSurface(MacBackend(window=f"^{title}$", timeout=20))
        state = s.observe()
        s.act(by(state, "Customer name", "fill"), state, text="Ada Lovelace")
        state = s.observe()
        s.act(by(state, "Save profile"), state)
        time.sleep(0.5)
        assert "saved Ada Lovelace" in s.observe()["text"]
    finally:
        process.kill()


@windows
def test_environment_probes_run_on_windows():
    from jev_context.act import desktop_policy as policy

    assert policy.desktop_locked() in (False, True)
    policy.check_elevation(__import__("os").getpid())  # same elevation as ourselves: never refused


@windows
@pytest.mark.desktop
def test_windows_modal_dialog_does_not_freeze_the_uia_channel(winforms):
    s = winforms
    state = s.observe()
    s.act(by(state, "Advanced"), state)
    s.settle({})
    state = s.observe()
    record = s.act(by(state, "Show help"), state)
    assert record["via"] == "bm_click"
    time.sleep(0.5)
    state = s.observe()  # must not hang while the MessageBox is open
    assert "Help" in state["dialogs"]
    ok = next(a for a in state["actions"] if a["label"] in ("OK", "确定"))
    s.act(ok, state)
    time.sleep(0.5)
    assert s.observe()["dialogs"] == []
