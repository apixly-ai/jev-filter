"""Never use a developer's configured ledger or remote counting mode in tests.

Tests marked `desktop` open real application windows and take keyboard focus, so they would
interrupt whoever is using the machine and can pick up their keystrokes. They are skipped unless
JEV_DESKTOP_TESTS=1 (set by the desktop CI jobs, or on a dedicated test machine).
"""

import os

import pytest


def pytest_collection_modifyitems(config, items):
    if os.environ.get("JEV_DESKTOP_TESTS") == "1":
        return
    skip = pytest.mark.skip(
        reason="opens real windows and takes focus; set JEV_DESKTOP_TESTS=1 to run"
    )
    for item in items:
        if "desktop" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def isolate_statistics(tmp_path, monkeypatch):
    monkeypatch.setenv("JEV_STATS_DIR", str(tmp_path / "isolated-statistics"))
    monkeypatch.delenv("JEV_STATS_DISABLED", raising=False)
