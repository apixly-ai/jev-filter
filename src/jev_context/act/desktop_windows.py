"""Windows UI Automation backend (the ``uiautomation`` package, a comtypes UIA client).

Measured on Windows 11 (single runs, magnitude only): a WinForms window with 27 elements walks
in ~140 ms; a Chrome window with 327 elements in ~1.5 s. pywinauto's UIA backend took 7 s to
find the same Notepad window, so it is not used.
"""

import re
import subprocess
import time

from .browser import ActionFailed, StalePage

try:  # optional dependency: jev-filter[desktop]
    import uiautomation as auto
except ImportError:  # pragma: no cover - exercised only without the extra
    auto = None

ROLE = {
    "ButtonControl": "button",
    "SplitButtonControl": "button",
    "CheckBoxControl": "checkbox",
    "RadioButtonControl": "radio",
    "EditControl": "textbox",
    "DocumentControl": "textbox",
    "ComboBoxControl": "combobox",
    "HyperlinkControl": "link",
    "ListItemControl": "option",
    "MenuItemControl": "menuitem",
    "TabItemControl": "tab",
    "TreeItemControl": "treeitem",
    "DataItemControl": "row",
}
TEXT_TYPES = {"TextControl", "StatusBarControl", "HeaderItemControl"}
SECTION_TYPES = {"GroupControl", "PaneControl", "TabItemControl", "ToolBarControl", "WindowControl"}


class Gone(RuntimeError):
    """The target window or element no longer exists."""


def _require():
    if auto is None:
        raise RuntimeError("desktop execution on Windows needs: pip install 'jev-filter[desktop]'")


def _pattern(control, name):
    try:
        return control.GetPattern(getattr(auto.PatternId, name))
    except Exception:
        return None


def _rect(control):
    r = control.BoundingRectangle
    return [r.left, r.top, r.right, r.bottom]


def list_windows():
    _require()
    rows = []
    for w in auto.GetRootControl().GetChildren():
        try:
            if w.ControlTypeName != "WindowControl" or not w.Name or w.IsOffscreen:
                continue
            rows.append({"title": w.Name, "pid": w.ProcessId, "class": w.ClassName})
        except Exception:
            continue
    return rows


class WindowsBackend:
    Gone = Gone

    def __init__(self, window=None, process=None, launch=None, timeout=15):
        _require()
        self.process = None
        if launch:
            import shutil

            launch = [shutil.which(launch[0]) or launch[0], *launch[1:]]
            self.process = subprocess.Popen(launch)
        self.pattern = re.compile(window, re.I) if window else None
        self.process_name = (process or "").lower()
        deadline = time.monotonic() + timeout
        self.window = None
        while time.monotonic() < deadline and self.window is None:
            self.window = self._find()
            if self.window is None:
                time.sleep(0.2)
        if self.window is None:
            self.close()
            raise RuntimeError("target window not found")
        self.pid = self.window.ProcessId
        self.last_focus = None

    def identity(self):
        return {
            "pid": self.pid,
            "process": self._process_name(self.pid),
            "window_class": self.window.ClassName,
        }

    def _find(self):
        for w in auto.GetRootControl().GetChildren():
            try:
                if w.ControlTypeName != "WindowControl" or not w.Name:
                    continue
                if (
                    self.process is not None
                    and w.ProcessId != self.process.pid
                    and not self.pattern
                ):
                    continue
                if self.pattern and not self.pattern.search(w.Name):
                    continue
                if self.process_name and self.process_name not in self._process_name(w.ProcessId):
                    continue
                return w
            except Exception:
                continue
        return None

    @staticmethod
    def _process_name(pid):
        try:
            import ctypes
            from ctypes import wintypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                return ""
            try:
                size = wintypes.DWORD(260)
                buf = ctypes.create_unicode_buffer(260)
                ctypes.windll.kernel32.QueryFullProcessImageNameW(
                    handle, 0, buf, ctypes.byref(size)
                )
                return buf.value.lower().rsplit("\\", 1)[-1]
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return ""

    def _process_windows(self):
        """Visible top-level HWNDs of the target process, via EnumWindows (UIA root enumeration
        over every desktop window took ~1.6 s on a busy desktop)."""
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        found = []
        proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def callback(hwnd, _):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == self.pid and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
            return True

        user32.EnumWindows(proc(callback), 0)
        return found

    def _roots(self):
        """The main window first, then this process's other top-level windows (dialogs, popups)."""
        try:
            if not self.window.Exists(0, 0):
                raise Gone("window closed")
        except Gone:
            raise
        except Exception:
            raise Gone("window closed") from None
        main = self.window.NativeWindowHandle
        roots = [self.window]
        for hwnd in self._process_windows():
            if hwnd == main:
                continue
            try:
                w = auto.ControlFromHandle(hwnd)
                if w is not None and w.ClassName != "SysShadow" and not w.IsOffscreen:
                    roots.insert(0, w)  # dialogs and popups are usually on top
            except Exception:
                continue
        return roots

    def window_info(self):
        roots = self._roots()
        self._cached_roots = roots
        focus = None
        try:
            f = auto.GetFocusedControl()
            if f is not None and f.ProcessId == self.pid:
                focus = f.Name
        except Exception:
            pass
        dialogs = [r.Name for r in roots if r is not self.window and r.Name]
        return {
            "title": self.window.Name,
            "pid": self.pid,
            "process": self._process_name(self.pid) or "app",
            "rect": _rect(self.window),
            "hwnd": self.window.NativeWindowHandle,
            "focus": focus,
            "dialogs": dialogs,
        }

    def describe(self, control, section="", owner=None):
        try:
            if control.IsOffscreen or not control.IsEnabled or control.IsPassword:
                return None
            ctype = control.ControlTypeName
            rect = _rect(control)
        except Exception:
            return None
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            return None
        role = ROLE.get(ctype)
        if role is None:
            return None
        label = (control.Name or control.HelpText or control.AutomationId or "").strip()[:200]
        element = {
            "role": role,
            "label": label,
            "section": section,
            "rect": rect,
            "enabled": True,
            "kinds": [],
        }
        value = _pattern(control, "ValuePattern")
        toggle = _pattern(control, "TogglePattern")
        selection = _pattern(control, "SelectionItemPattern")
        expand = _pattern(control, "ExpandCollapsePattern")
        if toggle is not None:
            element["checked"] = {0: False, 1: True}.get(toggle.ToggleState, "mixed")
        if selection is not None and role in ("radio", "tab", "option", "treeitem"):
            element["selected"] = bool(selection.IsSelected)
        if expand is not None:
            element["expanded"] = expand.ExpandCollapseState in (1, 2)
        if value is not None and role in ("textbox", "combobox"):
            try:
                element["value"] = (value.Value or "")[:200]
                writable = not value.IsReadOnly
            except Exception:
                writable = False
            if writable and role == "textbox":
                element["kinds"].append("fill")
            if role == "combobox":
                element["value_only"] = True
        if owner is not None and role == "option":
            element["kinds"] = ["select"]
            element["owner"] = owner.get("label")
            element["owner_value"] = owner.get("value", "")
        elif role == "combobox":
            element["kinds"].append("click")
            element["opens"] = True
        elif role != "textbox" or "fill" in element["kinds"]:
            element["kinds"].append("click")
        return element

    def snapshot(self, limit=400):
        elements, texts = [], []
        self.truncated = False
        deadline = time.monotonic() + 3.0
        seen = set()

        def walk(control, section, owner, depth, parent_key):
            if len(elements) >= limit or depth > 40:
                self.truncated = True
                return
            if time.monotonic() > deadline:
                self.truncated = True  # large trees (Electron/Chromium) are cut, never silently
                return
            try:
                children = control.GetChildren()
            except Exception:
                return
            for index, child in enumerate(children):
                try:
                    ctype = child.ControlTypeName
                    if ctype == "TitleBarControl" or child.IsOffscreen:
                        continue
                    if owner is not None and ctype == "ButtonControl":
                        continue  # a combo box's own drop-down button; "Open <combo>" covers it
                    name = (child.Name or "").strip()
                except Exception:
                    continue
                try:
                    runtime = child.GetRuntimeId()
                except Exception:
                    runtime = None
                # Virtual items (list/tab items) may have no runtime id; key them by tree path.
                key = (
                    "uia:" + ".".join(str(x) for x in runtime)
                    if runtime
                    else f"{parent_key}/{index}:{ctype}:{name[:40]}"
                )
                if ctype in TEXT_TYPES and name:
                    texts.append(name[:300])
                element = self.describe(child, section, owner)
                next_section = section
                next_owner = owner
                if element is not None:
                    if key not in seen and element["kinds"]:
                        seen.add(key)
                        element.update(node=key, handle=child)
                        elements.append(element)
                    if element["role"] == "combobox":
                        next_owner = element
                    if element["role"] == "textbox" and ctype == "DocumentControl":
                        texts.append((element.get("value") or "")[:2000])
                if ctype in SECTION_TYPES and name and ctype != "WindowControl":
                    next_section = name[:120]
                walk(child, next_section, next_owner, depth + 1, key)

        roots = getattr(self, "_cached_roots", None) or self._roots()
        self._cached_roots = None
        for root in roots:
            try:
                root_key = "uia:" + ".".join(str(x) for x in root.GetRuntimeId())
            except Exception:
                root_key = "root"
            # A combo box's drop-down list is its own top-level popup (class ComboLBox) named after
            # the combo box; its items are options of that combo, like a native <select>.
            owner = None
            try:
                if root is not self.window and root.ControlTypeName == "ListControl":
                    owner = {"label": (root.Name or "List")[:120], "value": ""}
            except Exception:
                owner = None
            walk(root, root.Name[:120] if root is not self.window else "", owner, 0, root_key)
        texts.insert(0, self.window.Name)
        return elements, texts

    def controls(self, window):
        extras = []
        focus = None
        try:
            focus = auto.GetFocusedControl()
        except Exception:
            pass
        if focus is not None and getattr(focus, "ProcessId", None) == self.pid:
            try:
                if focus.ControlTypeName in ("EditControl", "DocumentControl", "ComboBoxControl"):
                    label = focus.Name or "field"
                    extras.append(
                        {
                            "id": "press_enter",
                            "kind": "key",
                            "key": "Enter",
                            "label": f"Press Enter in the focused field ({label})",
                        }
                    )
            except Exception:
                pass
        extras.append(
            {
                "id": "press_escape",
                "kind": "key",
                "key": "Escape",
                "label": "Press Escape (close a menu, popup or dialog without confirming)",
            }
        )
        return extras

    # -- execution ------------------------------------------------------------------------------
    def _activate(self):
        try:
            self.window.SetActive()
        except Exception:
            pass

    def _pointer_click(self, control):
        rect = _rect(control)
        x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
        self._activate()
        hit = auto.ControlFromPoint(x, y)
        target = control.GetRuntimeId()
        node = hit
        for _ in range(12):
            if node is None:
                break
            try:
                if node.GetRuntimeId() == target:
                    break
                node = node.GetParentControl()
            except Exception:
                node = None
        if node is None:
            raise StalePage("target covered")
        auto.Click(x, y, waitTime=0)
        return {"via": "pointer"}

    def pointer_click_at(self, x, y):
        """Click a screen point only if the window under it belongs to the target process."""
        import ctypes
        from ctypes import wintypes

        self._activate()
        user32 = ctypes.windll.user32
        hwnd = user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != self.pid:
            raise StalePage("point is covered by another window")
        auto.Click(int(x), int(y), waitTime=0)

    @staticmethod
    def _post_click(control, hwnd):
        """Standard Win32/WinForms buttons: send BM_CLICK with a 1 s timeout.

        Measured on a WinForms fixture: a UIA Invoke on a button whose handler shows a modal
        MessageBox never returned while the box was open, and every later UIA call to that
        application hung as well. SendMessageTimeout(BM_CLICK) returns after at most 1 s in that
        case and leaves the UIA channel usable (the dialog is then observed and closed normally);
        for ordinary buttons it returns in a few ms. A posted BM_CLICK was ignored by a
        background dialog, so the synchronous-with-timeout form is used.
        """
        try:
            if (
                control.ControlTypeName != "ButtonControl"
                or "button" not in (control.ClassName or "").lower()
            ):
                return False
            import ctypes
            from ctypes import wintypes

            result = wintypes.DWORD()
            sent = ctypes.windll.user32.SendMessageTimeoutW(
                hwnd,
                0x00F5,
                0,
                0,
                0x0002,
                1000,
                ctypes.byref(result),  # BM_CLICK, SMTO_ABORTIFHUNG
            )
            # 0 with ERROR_TIMEOUT means the handler is still running (modal): it was delivered.
            return bool(sent) or ctypes.windll.kernel32.GetLastError() == 1460
        except Exception:
            return False

    def _invoke_isolated(self, control, pattern, timeout=2.0):
        """Invoke without letting a modal dialog freeze this process.

        A provider may run the click handler synchronously; if that handler shows a modal
        dialog, Invoke only returns when the dialog closes (measured: still blocked after 6 s on
        a WinForms MessageBox, and later UIA calls on the same thread hung too). HWND-backed
        controls are therefore re-acquired and invoked from a worker thread with its own UIA
        client; after `timeout` the step counts as executed and the next observation sees the
        dialog among the process's windows.
        """
        import threading

        try:
            hwnd = control.NativeWindowHandle
        except Exception:
            hwnd = 0
        if not hwnd:
            pattern.Invoke(waitTime=0)
            return {"via": "invoke"}
        # Buttons of the main window may open a modal dialog: BM_CLICK keeps UIA usable. Buttons
        # inside a dialog or popup usually close it; BM_CLICK can be ignored by an inactive dialog
        # (documented for BM_CLICK, and observed intermittently), so those use Invoke.
        try:
            top = control.GetTopLevelControl()
            in_main_window = (
                top is not None and top.NativeWindowHandle == self.window.NativeWindowHandle
            )
        except Exception:
            in_main_window = False
        if in_main_window and self._post_click(control, hwnd):
            return {"via": "bm_click"}
        outcome = {}

        def work():
            with auto.UIAutomationInitializerInThread():
                try:
                    target = auto.ControlFromHandle(hwnd)
                    invoke = target.GetPattern(auto.PatternId.InvokePattern) if target else None
                    if invoke is None:
                        outcome["missing"] = True
                        return
                    invoke.Invoke(waitTime=0)
                    outcome["ok"] = True
                except Exception as error:  # reported to the archive, never retried blindly
                    outcome["error"] = type(error).__name__

        worker = threading.Thread(target=work, daemon=True, name="jev-uia-invoke")
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            return {"via": "invoke", "blocked_by_modal": True}
        if outcome.get("missing"):
            pattern.Invoke(waitTime=0)
            return {"via": "invoke"}
        if outcome.get("error"):
            raise ActionFailed(f"invoke failed: {outcome['error']}")
        return {"via": "invoke"}

    def perform(self, control, kind, text=None):
        try:
            if not control.Exists(0, 0):
                raise StalePage("element gone")
        except StalePage:
            raise
        except Exception:
            raise StalePage("element gone") from None
        if kind == "fill":
            value = _pattern(control, "ValuePattern")
            if value is not None and not value.IsReadOnly:
                value.SetValue(text, waitTime=0)
                if not control.IsPassword and (value.Value or "") != text:
                    return {"via": "value", "readback_mismatch": True}
                self.last_focus = control
                return {"via": "value"}
            self._pointer_click(control)
            auto.SendKeys("{Ctrl}a", waitTime=0)
            auto.SendKeys(text.replace("{", "{{}").replace("}", "{}}"), waitTime=0)
            self.last_focus = control
            return {"via": "keyboard"}
        if kind == "select":
            selection = _pattern(control, "SelectionItemPattern")
            if selection is None:
                return self._pointer_click(control)
            selection.Select(waitTime=0)
            return {"via": "selection"}
        for name, call in (
            ("InvokePattern", lambda p: p.Invoke(waitTime=0)),
            ("TogglePattern", lambda p: p.Toggle(waitTime=0)),
            ("SelectionItemPattern", lambda p: p.Select(waitTime=0)),
            (
                "ExpandCollapsePattern",
                lambda p: (
                    p.Collapse(waitTime=0)
                    if p.ExpandCollapseState in (1, 2)
                    else p.Expand(waitTime=0)
                ),
            ),
        ):
            pattern = _pattern(control, name)
            if pattern is not None:
                if name == "InvokePattern":
                    return self._invoke_isolated(control, pattern)
                call(pattern)
                return {"via": name.replace("Pattern", "").lower()}
        # A collapsed combo box without ExpandCollapse opens through its drop-down button.
        try:
            button = control.ButtonControl(searchDepth=1)
            if button.Exists(0, 0):
                invoke = _pattern(button, "InvokePattern")
                if invoke is not None:
                    invoke.Invoke(waitTime=0)
                    return {"via": "invoke"}
        except Exception:
            pass
        return self._pointer_click(control)

    def control(self, action):
        if action["kind"] == "key":
            self._activate()
            if self.last_focus is not None:
                try:
                    self.last_focus.SetFocus()
                except Exception:
                    pass
            auto.SendKeys("{" + action["key"] + "}", waitTime=0)
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
