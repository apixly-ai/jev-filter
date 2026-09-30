"""Explicit setup diagnostics. Offline by default; no credentials in output."""

import importlib.util
import shutil
import sys

from . import __version__
from .provider import Client, ProviderError, credential


def hosted():
    """Readiness of browser/desktop execution. Offline; reads nothing but local capabilities."""
    from .act import desktop_policy

    report = {"stop_file_present": desktop_policy.stop_file().exists()}
    try:
        from .act.cdp import CDPError, find_chromium

        report["browser_executable"] = bool(find_chromium())
    except CDPError:
        report["browser_executable"] = False
    if sys.platform == "win32":
        report["desktop_backend"] = importlib.util.find_spec("uiautomation") is not None
        report["ocr"] = importlib.util.find_spec("winrt.windows.media.ocr") is not None
        report["session_locked"] = desktop_policy.desktop_locked()
        try:
            report["elevated"] = bool(desktop_policy._elevated())
        except Exception:
            report["elevated"] = None
    elif sys.platform == "darwin":  # pragma: no cover - macOS only
        report["desktop_backend"] = importlib.util.find_spec("ApplicationServices") is not None
        report["ocr"] = importlib.util.find_spec("Vision") is not None
        if report["desktop_backend"]:
            try:
                import ApplicationServices as AS
                import Quartz

                report["accessibility_trusted"] = bool(AS.AXIsProcessTrusted())
                report["screen_capture_allowed"] = bool(Quartz.CGPreflightScreenCaptureAccess())
            except Exception:
                report["accessibility_trusted"] = None
    else:
        report["desktop_backend"] = False
        report["desktop_note"] = "desktop execution supports Windows and macOS"
    return report


def check(live=False):
    try:
        credential()
        configured = True
    except ProviderError:
        configured = False
    result = {
        "ok": True,
        "version": __version__,
        "python": sys.version.split()[0],
        "api_key_configured": configured,
        "ripgrep": shutil.which("rg") is not None,
        "tree_sitter": importlib.util.find_spec("tree_sitter") is not None,
        "live_checked": False,
        "result_cache": False,
        "concurrency_cap": 30,
        "hosted": hosted(),
    }
    if live:
        try:
            with Client() as client:
                response = client.call(
                    {
                        "model": "jev-1.13.0",
                        "state": "The traffic light is red.",
                        "questions": {
                            "color": {
                                "type": "choice",
                                "instructions": "Select the observed color.",
                                "criteria": {"red": "Red", "green": "Green"},
                            }
                        },
                    }
                )
            result.update(
                live_checked=True,
                ok=response["answers"]["color"]["choice"] == "red",
                model=response["model"],
                usage=response["usage"],
                usage_complete=response["usage_complete"],
            )
        except ProviderError as error:
            result.update(ok=False, error_code=error.code)
    return result
