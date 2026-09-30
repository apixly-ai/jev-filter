"""Desktop surfaces for hosted execution: the same observe/fresh/act contract as a browser page.

A platform backend enumerates accessibility elements of ONE target application (its main window
plus its own popups and dialogs). Each element becomes an indexed action with the same shape the
browser page script produces, so the kernel, the action space and the irreversible gate are
shared. Execution prefers accessibility patterns (invoke, toggle, select, set value), which need
no pointer movement or focus, and only falls back to a pointer click after hit-testing that the
point still belongs to the target element.
"""

import hashlib
import json
import sys
import time

from .browser import ActionFailed, StalePage, fingerprint


def signature(element):
    """Identity for freshness: what the element is and its state, not where it was found."""
    keep = ("role", "label", "value", "checked", "selected", "expanded", "enabled", "rect")
    row = [element.get(k) for k in keep]
    if element.get("sensitive"):
        row[2] = bool(row[2])  # presence only: secrets never enter markers or guards
    return row


class DesktopSurface:
    """Generic surface over a platform backend (Windows UI Automation, macOS Accessibility)."""

    name = "desktop"

    def __init__(self, backend, *, ocr=None, ocr_min_actions=2, settle_s=0.15):
        self.backend = backend
        self.ocr = ocr
        self.ocr_min_actions = ocr_min_actions
        self.settle_s = settle_s
        self.nodes = {}
        self.dialogs = []

    # -- observation --------------------------------------------------------------------------
    def _collect(self, limit, text_limit):
        window = self.backend.window_info()
        elements, texts = self.backend.snapshot(limit=max(limit * 2, 400))
        actions = []
        nodes = {}
        omitted = 0
        for element in elements:
            node = element["node"]
            nodes[node] = element["handle"]
            base = {
                "node": node,
                "role": element["role"],
                "label": element["label"] or element["role"],
                "section": element.get("section") or "",
            }
            for key in ("checked", "selected", "expanded"):
                if element.get(key) is not None:
                    base[key] = str(element[key]).lower()
            if element.get("source"):
                base["source"] = element["source"]
            for kind in element["kinds"]:
                if len(actions) >= limit:
                    omitted += 1
                    continue
                action = {**base, "kind": kind}
                if kind == "fill":
                    action["value"] = element.get("value", "")
                    if element.get("sensitive"):
                        action["sensitive"] = True
                        action["value"] = "[filled]" if element.get("value") else ""
                elif kind == "select":
                    action["label"] = f"{element.get('owner') or 'List'} → {base['label']}"
                    action["current_value"] = element.get("owner_value", "")
                    action["value"] = base["label"]
                elif kind == "click" and "fill" in element["kinds"]:
                    action["label"] = "Focus " + base["label"]
                elif kind == "click" and element.get("opens"):
                    action["label"] = "Open " + base["label"]
                actions.append(action)
        if self.ocr is not None and len(actions) < self.ocr_min_actions:
            for line in self.ocr.lines(window):
                node = "ocr:" + hashlib.sha1(json.dumps(line["rect"]).encode()).hexdigest()[:12]
                nodes[node] = {"ocr": line}
                actions.append(
                    {
                        "node": node,
                        "role": "text",
                        "label": line["text"],
                        "section": "",
                        "kind": "click",
                        "source": "ocr",
                        "rect": line["rect"],
                    }
                )
                texts.append(line["text"])
        for i, action in enumerate(actions):
            action["id"] = f"e{i + 1}"
        actions.extend(self.backend.controls(window))
        actions.append({"id": "wait", "kind": "wait", "label": "Wait for the window to update"})
        text = "\n".join(t for t in texts if t)[:text_limit]
        return window, actions, nodes, text, omitted, elements

    def observe(self, limit=250, text_limit=6000, scope=None):
        try:
            window, actions, nodes, text, omitted, elements = self._collect(limit, text_limit)
        except self.backend.Gone:
            raise StalePage("target window is gone") from None
        self.nodes = nodes
        guards = {str(e["node"]): signature(e) for e in elements}
        marker = [window.get("title"), window.get("focus"), [signature(e) for e in elements], text]
        state = {
            "url": f"window://{window.get('process', 'app')}/{window.get('title', '')}",
            "title": window.get("title"),
            "text": text,
            "actions": actions,
            "scroll": {"y": window.get("scroll", 0)},
            "marker": marker,
            "page_key": [window.get("title"), window.get("pid")],
            "guards": guards,
            "omitted_actions": omitted,
            "dialogs": window.get("dialogs", []),
            "window": {k: window.get(k) for k in ("title", "process", "pid", "rect")},
        }
        state["fingerprint"] = fingerprint(state)
        return state

    def fresh(self, state, action=None):
        if (
            action is not None
            and action.get("node") in self.nodes
            and action.get("source") != "ocr"
        ):
            try:
                current = self.backend.describe(self.nodes[action["node"]])
            except Exception:
                return False
            return current is not None and signature(current) == state["guards"].get(
                str(action["node"])
            )
        if action is not None and action.get("source") == "ocr":
            return self.ocr.unchanged(action["rect"])
        try:
            return self.observe(limit=len(state["actions"]) + 50)["marker"] == state["marker"]
        except StalePage:
            return False

    def settle(self, action):
        """Wait until two consecutive snapshots agree (capped), or a short fixed delay."""
        time.sleep(self.settle_s)
        deadline = time.monotonic() + 1.0
        try:
            last = self.observe(limit=400)["marker"]
            while time.monotonic() < deadline:
                time.sleep(0.08)
                current = self.observe(limit=400)["marker"]
                if current == last:
                    return
                last = current
        except StalePage:
            pass

    def extract(self, scope=None, limit=500):
        state = self.observe(limit=limit)
        records = [
            {"id": a["id"], "kind": a["kind"], "text": a["label"], "section": a.get("section", "")}
            for a in state["actions"]
            if "node" in a
        ]
        records += [
            {"id": f"t{i + 1}", "kind": "text", "text": line}
            for i, line in enumerate(state["text"].splitlines())
            if line.strip()
        ]
        return {
            "records": records[:limit],
            "omitted": max(0, len(records) - limit),
            "url": state["url"],
            "title": state["title"],
        }

    # -- execution ----------------------------------------------------------------------------
    def act(self, action, state, text=None):
        kind = action["kind"]
        if kind == "wait":
            time.sleep(0.2)
            return {"executed": action["id"]}
        if kind in ("click", "select", "fill") and not self.fresh(state, action):
            raise StalePage("element changed since this decision")
        if kind == "fill" and not isinstance(text, str):
            raise ValueError("fill requires program-supplied text")
        try:
            if action.get("source") == "ocr":
                record = self.ocr.click(action["rect"], self.backend)
            elif kind in ("click", "select", "fill"):
                record = self.backend.perform(self.nodes[action["node"]], kind, text)
            else:
                record = self.backend.control(action)
        except self.backend.Gone:
            raise StalePage("target window is gone") from None
        except StalePage:
            raise
        except ActionFailed:
            raise
        except Exception as error:
            raise ActionFailed(f"{kind} failed: {type(error).__name__}") from None
        return {"executed": action["id"], **(record or {})}

    def close(self):
        self.backend.close()


def open_backend(window=None, process=None, launch=None, timeout=15):
    if sys.platform == "win32":
        from .desktop_windows import WindowsBackend

        return WindowsBackend(window=window, process=process, launch=launch, timeout=timeout)
    if sys.platform == "darwin":
        from .desktop_macos import MacBackend

        return MacBackend(window=window, process=process, launch=launch, timeout=timeout)
    raise RuntimeError("desktop execution supports Windows and macOS")


def list_windows():
    if sys.platform == "win32":
        from .desktop_windows import list_windows as win_list

        return win_list()
    if sys.platform == "darwin":
        from .desktop_macos import list_windows as mac_list

        return mac_list()
    raise RuntimeError("desktop execution supports Windows and macOS")
