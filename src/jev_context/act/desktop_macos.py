"""macOS Accessibility (AX) backend through pyobjc.

The process running jev-filter (Terminal, iTerm, an IDE or Python itself) must be granted
System Settings → Privacy & Security → Accessibility. All AX calls go through ``AXApi`` so the
walking, describing and execution logic can be exercised with a fake tree on any platform.
"""

import subprocess
import time

from .browser import ActionFailed, StalePage

ROLE = {
    "AXButton": "button",
    "AXMenuButton": "button",
    "AXCheckBox": "checkbox",
    "AXRadioButton": "radio",
    "AXTextField": "textbox",
    "AXTextArea": "textbox",
    "AXSearchField": "searchbox",
    "AXComboBox": "combobox",
    "AXPopUpButton": "combobox",
    "AXLink": "link",
    "AXMenuItem": "menuitem",
    "AXCell": "option",
    "AXRow": "row",
    "AXDisclosureTriangle": "button",
    "AXIncrementor": "spinbutton",
}
TEXT_ROLES = {"AXStaticText", "AXHeading"}
SECTION_ROLES = {"AXGroup", "AXTabGroup", "AXSheet", "AXScrollArea", "AXSplitGroup", "AXToolbar"}


class Gone(RuntimeError):
    """The target application or window no longer exists."""


class AXApi:  # pragma: no cover - pyobjc adapter; exercised only on macOS runners
    """Thin adapter over pyobjc's ApplicationServices/Quartz/AppKit."""

    def __init__(self):
        try:
            import AppKit
            import ApplicationServices as AS
            import Quartz
        except ImportError:
            raise RuntimeError(
                "desktop execution on macOS needs: pip install 'jev-filter[desktop]'"
            ) from None
        self.AS, self.Quartz, self.AppKit = AS, Quartz, AppKit

    def trusted(self, prompt=False):
        options = {self.AS.kAXTrustedCheckOptionPrompt: bool(prompt)}
        return bool(self.AS.AXIsProcessTrustedWithOptions(options))

    def applications(self):
        # runningApplications is a KVO snapshot refreshed on the run loop; turn it briefly so an
        # application launched after the first query (for example by --launch) shows up.
        self.AppKit.NSRunLoop.currentRunLoop().runUntilDate_(
            self.AppKit.NSDate.dateWithTimeIntervalSinceNow_(0.02)
        )
        for app in self.AppKit.NSWorkspace.sharedWorkspace().runningApplications():
            yield {"pid": int(app.processIdentifier()), "name": str(app.localizedName() or "")}

    def app(self, pid):
        element = self.AS.AXUIElementCreateApplication(pid)
        # A busy or hung application must not stall every attribute read for seconds.
        self.AS.AXUIElementSetMessagingTimeout(element, 0.5)
        return element

    def get(self, element, attribute):
        error, value = self.AS.AXUIElementCopyAttributeValue(element, attribute, None)
        if error == -25211:  # kAXErrorAPIDisabled: permission revoked mid-run; never "empty"
            raise RuntimeError(
                "accessibility_permission_required: Accessibility access was revoked"
            )
        return value if error == 0 else None

    def point(self, value):
        ok, p = self.AS.AXValueGetValue(value, self.AS.kAXValueCGPointType, None)
        return (p.x, p.y) if ok else None

    def size(self, value):
        ok, s = self.AS.AXValueGetValue(value, self.AS.kAXValueCGSizeType, None)
        return (s.width, s.height) if ok else None

    def actions(self, element):
        error, names = self.AS.AXUIElementCopyActionNames(element, None)
        return list(names or []) if error == 0 else []

    def perform(self, element, action):
        return self.AS.AXUIElementPerformAction(element, action) == 0

    def set(self, element, attribute, value):
        return self.AS.AXUIElementSetAttributeValue(element, attribute, value) == 0

    def settable(self, element, attribute):
        error, ok = self.AS.AXUIElementIsAttributeSettable(element, attribute, None)
        return error == 0 and bool(ok)

    def pid_at(self, x, y):
        system = self.AS.AXUIElementCreateSystemWide()
        error, element = self.AS.AXUIElementCopyElementAtPosition(system, x, y, None)
        if error != 0 or element is None:
            return None
        error, pid = self.AS.AXUIElementGetPid(element, None)
        return pid if error == 0 else None

    def click(self, x, y):
        Q = self.Quartz
        for kind in (Q.kCGEventLeftMouseDown, Q.kCGEventLeftMouseUp):
            event = Q.CGEventCreateMouseEvent(None, kind, (x, y), Q.kCGMouseButtonLeft)
            Q.CGEventPost(Q.kCGHIDEventTap, event)
            time.sleep(0.02)

    def key(self, pid, keycode):
        Q = self.Quartz
        for down in (True, False):
            event = Q.CGEventCreateKeyboardEvent(None, keycode, down)
            Q.CGEventPostToPid(pid, event)

    def activate(self, pid):
        app = self.AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is not None:
            app.activateWithOptions_(self.AppKit.NSApplicationActivateIgnoringOtherApps)


KEYCODES = {"Enter": 36, "Escape": 53}


def list_windows(api=None):  # pragma: no cover - needs a real AX session
    api = api or AXApi()
    rows = []
    for app in api.applications():
        windows = api.get(api.app(app["pid"]), "AXWindows") or []
        for w in windows:
            title = api.get(w, "AXTitle")
            if title:
                rows.append({"title": str(title), "pid": app["pid"], "process": app["name"]})
    return rows


class MacBackend:
    Gone = Gone

    def __init__(self, window=None, process=None, launch=None, timeout=15, api=None):
        import re

        self.api = api or AXApi()
        if not self.api.trusted(prompt=True):
            raise RuntimeError(
                "accessibility_permission_required: allow this terminal/app in System Settings → "
                "Privacy & Security → Accessibility, then retry"
            )
        self.process = subprocess.Popen(launch) if launch else None
        self.pattern = re.compile(window, re.I) if window else None
        self.process_name = (process or "").lower()
        deadline = time.monotonic() + timeout
        self.pid, self.window = None, None
        while time.monotonic() < deadline and self.window is None:
            self._find()
            if self.window is None:
                time.sleep(0.2)
        if self.window is None:
            self.close()
            raise RuntimeError("target window not found")
        self.name = self._app_name()

    def identity(self):
        return {"pid": self.pid, "process": self.name, "window_class": None}

    def _app_name(self):
        for app in self.api.applications():
            if app["pid"] == self.pid:
                return app["name"]
        return "app"

    def _find(self):
        for app in self.api.applications():
            if self.process is not None and app["pid"] != self.process.pid and not self.pattern:
                continue
            if self.process_name and self.process_name not in app["name"].lower():
                continue
            for w in self.api.get(self.api.app(app["pid"]), "AXWindows") or []:
                title = str(self.api.get(w, "AXTitle") or "")
                if self.pattern and not self.pattern.search(title):
                    continue
                self.pid, self.window = app["pid"], w
                return

    def _roots(self):
        app = self.api.app(self.pid)
        windows = self.api.get(app, "AXWindows")
        if windows is None:
            raise Gone("application gone")
        title = self.api.get(self.window, "AXTitle")
        if title is None:
            # The window object went stale; rebind by title pattern if possible.
            self._find()
            if self.window is None:
                raise Gone("window closed")
        roots = [self.window]
        for w in windows:
            if w != self.window and self.api.get(w, "AXSubrole") in ("AXDialog", "AXSystemDialog"):
                roots.insert(0, w)
        return roots

    def _rect(self, element):
        position = self.api.get(element, "AXPosition")
        size = self.api.get(element, "AXSize")
        if position is None or size is None:
            return None
        (x, y), (w, h) = self.api.point(position) or (0, 0), self.api.size(size) or (0, 0)
        return [round(x), round(y), round(x + w), round(y + h)]

    def window_info(self):
        roots = self._roots()
        self._cached_roots = roots
        focused = self.api.get(self.api.app(self.pid), "AXFocusedUIElement")
        focus = (
            str(self.api.get(focused, "AXTitle") or self.api.get(focused, "AXDescription") or "")
            if focused
            else None
        )
        return {
            "title": str(self.api.get(self.window, "AXTitle") or ""),
            "pid": self.pid,
            "process": self.name,
            "rect": self._rect(self.window),
            "focus": focus,
            "dialogs": [
                str(self.api.get(r, "AXTitle") or "dialog") for r in roots if r is not self.window
            ],
        }

    def describe(self, element, section="", owner=None):
        role_name = self.api.get(element, "AXRole")
        role = ROLE.get(str(role_name or ""))
        if role is None or self.api.get(element, "AXSubrole") == "AXSecureTextField":
            return None
        if self.api.get(element, "AXEnabled") is False:
            return None
        rect = self._rect(element)
        if not rect or rect[2] <= rect[0] or rect[3] <= rect[1]:
            return None
        label = ""
        for attribute in ("AXTitle", "AXDescription", "AXHelp", "AXPlaceholderValue"):
            value = self.api.get(element, attribute)
            if value:
                label = str(value)
                break
        if not label:
            title_element = self.api.get(element, "AXTitleUIElement")
            if title_element is not None:
                label = str(self.api.get(title_element, "AXValue") or "")
        element_info = {
            "role": role,
            "label": label.strip()[:200],
            "section": section,
            "rect": rect,
            "enabled": True,
            "kinds": [],
        }
        value = self.api.get(element, "AXValue")
        if role in ("checkbox", "radio"):
            element_info["checked"] = bool(value) if value in (0, 1, True, False) else "mixed"
            element_info["kinds"].append("click")
        elif role in ("textbox", "searchbox", "combobox"):
            element_info["value"] = str(value or "")[:200]
            if role != "combobox" or str(role_name) == "AXComboBox":
                if self.api.settable(element, "AXValue"):
                    element_info["kinds"].append("fill")
            if role == "combobox":
                element_info["kinds"].append("click")
                element_info["opens"] = True
            elif "fill" in element_info["kinds"]:
                element_info["kinds"].append("click")
        elif owner is not None and role in ("menuitem", "option"):
            element_info["kinds"] = ["select"]
            element_info["owner"] = owner.get("label")
            element_info["owner_value"] = owner.get("value", "")
        else:
            element_info["kinds"].append("click")
        return element_info

    def snapshot(self, limit=400):
        elements, texts = [], []
        self.truncated = False
        deadline = time.monotonic() + 3.0

        def walk(element, section, owner, depth, key):
            if len(elements) >= limit or depth > 40:
                self.truncated = True
                return
            if time.monotonic() > deadline:
                self.truncated = True  # large trees (Electron/Chromium) are cut, never silently
                return
            for index, child in enumerate(self.api.get(element, "AXChildren") or []):
                role_name = str(self.api.get(child, "AXRole") or "")
                child_key = f"{key}/{index}:{role_name}"
                if role_name in TEXT_ROLES:
                    text = self.api.get(child, "AXValue") or self.api.get(child, "AXTitle")
                    if text:
                        texts.append(str(text)[:300])
                info = self.describe(child, section, owner)
                next_section, next_owner = section, owner
                if info is not None:
                    info.update(node="ax:" + child_key, handle=child)
                    elements.append(info)
                    if info["role"] == "combobox":
                        next_owner = info
                if role_name in SECTION_ROLES:
                    title = self.api.get(child, "AXTitle") or self.api.get(child, "AXDescription")
                    if title:
                        next_section = str(title)[:120]
                walk(child, next_section, next_owner, depth + 1, child_key)

        roots = getattr(self, "_cached_roots", None) or self._roots()
        self._cached_roots = None
        for i, root in enumerate(roots):
            walk(
                root,
                "" if root is self.window else str(self.api.get(root, "AXTitle") or ""),
                None,
                0,
                f"w{i}",
            )
        texts.insert(0, str(self.api.get(self.window, "AXTitle") or ""))
        return elements, texts

    def controls(self, window):
        extras = []
        focused = self.api.get(self.api.app(self.pid), "AXFocusedUIElement")
        if focused is not None and str(self.api.get(focused, "AXRole") or "") in (
            "AXTextField",
            "AXTextArea",
            "AXComboBox",
            "AXSearchField",
        ):
            extras.append(
                {
                    "id": "press_enter",
                    "kind": "key",
                    "key": "Enter",
                    "label": "Press Return in the focused field",
                }
            )
        extras.append(
            {
                "id": "press_escape",
                "kind": "key",
                "key": "Escape",
                "label": "Press Escape (close a menu, popup or dialog without confirming)",
            }
        )
        return extras

    def pointer_click_at(self, x, y):
        self.api.activate(self.pid)
        if self.api.pid_at(x, y) != self.pid:
            raise StalePage("point is covered by another application")
        self.api.click(x, y)

    def perform(self, element, kind, text=None):
        if self.api.get(element, "AXRole") is None:
            raise StalePage("element gone")
        if kind == "fill":
            if self.api.settable(element, "AXValue") and self.api.set(element, "AXValue", text):
                back = self.api.get(element, "AXValue")
                return {
                    "via": "value",
                    **({"readback_mismatch": True} if str(back) != text else {}),
                }
            raise ActionFailed("field is not settable")
        names = self.api.actions(element)
        for action in (
            ("AXPick", "AXPress", "AXShowMenu", "AXConfirm")
            if kind == "select"
            else ("AXPress", "AXPick", "AXShowMenu", "AXConfirm")
        ):
            if action in names and self.api.perform(element, action):
                return {"via": action[2:].lower()}
        rect = self._rect(element)
        if rect is None:
            raise StalePage("element gone")
        self.pointer_click_at((rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2)
        return {"via": "pointer"}

    def control(self, action):
        if action["kind"] == "key":
            self.api.activate(self.pid)
            self.api.key(self.pid, KEYCODES[action["key"]])
            return {"via": "keyboard"}
        raise ActionFailed(f"unsupported control {action['kind']}")

    def close(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
