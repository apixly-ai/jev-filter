"""browse / desktop / extract CLI wiring and the optional text helper, without paid calls."""

import json

import httpx
import pytest

from jev_context.act import cli, text
from tests.test_act_kernel import SEARCH, Policy, page, search_flow


class FakeClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def fake_decider(script):
    policy = Policy(script)
    policy.client = FakeClient()
    return policy


def run_cli(monkeypatch, capsys, argv, surface, script):
    decide = fake_decider(script)
    monkeypatch.setattr(cli, "jev_decider", lambda: decide)
    monkeypatch.setattr(cli, "open_page", lambda args: surface)
    monkeypatch.setattr(cli, "open_desktop", lambda args: surface)
    code = cli.main(argv)
    return code, json.loads(capsys.readouterr().out), decide


def closable(surface):
    surface.name = "cdp"
    surface.closed = []
    surface.close = lambda close_browser=False: surface.closed.append(close_browser)
    return surface


def test_load_values_from_file_stdin_and_pairs(tmp_path, monkeypatch):
    path = tmp_path / "v.json"
    path.write_text('{"card": {"value": "4111", "sensitive": true}}', encoding="utf-8")
    values = cli.load_values(str(path), ["query=red shoes"])
    assert values == {"card": {"value": "4111", "sensitive": True}, "query": "red shoes"}
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO('{"a": "b"}'))
    assert cli.load_values("-", None) == {"a": "b"}
    for bad in (["novalue"], ["=x"]):
        with pytest.raises(ValueError):
            cli.load_values(None, bad)
    path.write_text('{"k": {"sensitive": true}}', encoding="utf-8")
    with pytest.raises(ValueError, match="value"):
        cli.load_values(str(path), None)
    path.write_text("[1]", encoding="utf-8")
    with pytest.raises(ValueError, match="object"):
        cli.load_values(str(path), None)


def test_browse_runs_the_kernel_and_prints_a_compact_packet(monkeypatch, capsys):
    surface = closable(search_flow())
    code, packet, decide = run_cli(
        monkeypatch,
        capsys,
        [
            "browse",
            "--url",
            "https://shop.test/",
            "--goal",
            "Search red shoes",
            "--value",
            "query=red shoes",
            "--verify-text",
            "results for red shoes",
        ],
        surface,
        [("TYPE_TEXT", "Search products", "query"), ("CLICK", "Search"), ("DONE",)],
    )
    assert code == 0 and packet["status"] == "done" and packet["verification"]["passed"]
    assert [t["operation"] for t in packet["trace"]] == ["TYPE_TEXT", "CLICK"]
    assert "history" not in packet and "decision_log" not in packet and packet["archive"]
    archived = json.loads(open(packet["archive"], encoding="utf-8").read())
    assert archived["result"]["decision_log"] and decide.client.closed and surface.closed == [False]


def test_browse_keeps_a_session_open_and_closes_attached_browsers(monkeypatch, capsys):
    surface = closable(search_flow())
    surface.detach = lambda: {"cdp_port": 9222, "target_id": "T"}
    code, packet, _ = run_cli(
        monkeypatch,
        capsys,
        ["browse", "--url", "https://shop.test/", "--goal", "x", "--keep-open"],
        surface,
        [("BLOCKED",)],
    )
    assert (
        code == 2
        and packet["session"] == {"cdp_port": 9222, "target_id": "T"}
        and surface.closed == []
    )
    surface = closable(search_flow())
    run_cli(
        monkeypatch,
        capsys,
        ["browse", "--url", "https://shop.test/", "--goal", "x", "--close-browser"],
        surface,
        [("BLOCKED",)],
    )
    assert surface.closed == [True]


def test_browse_argument_errors(monkeypatch):
    monkeypatch.setattr(cli, "jev_decider", lambda: fake_decider([]))
    monkeypatch.setattr(cli, "open_page", lambda args: closable(search_flow()))
    with pytest.raises(ValueError, match="--url"):
        cli.main(["browse", "--goal", "x"])
    with pytest.raises(ValueError, match="budgets"):
        cli.main(["browse", "--url", "https://a.test/", "--goal", "x", "--max-steps", "0"])
    for name in ("JEV_TEXT_BASE_URL", "JEV_TEXT_API_KEY", "JEV_TEXT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="text-model"):
        cli.main(["browse", "--url", "https://a.test/", "--goal", "x", "--text-model"])


def test_invalid_uncertainty_cleans_up_open_surface_and_text_client(tmp_path, monkeypatch):
    path = tmp_path / "broken-policy.json"
    path.write_text("{")
    surface = closable(search_flow())
    helper = helper_with(chat('{"text": null}'))
    monkeypatch.setattr(cli, "open_page", lambda args: surface)
    monkeypatch.setattr(text, "from_environment", lambda: helper)
    monkeypatch.setattr(cli, "jev_decider", lambda: fake_decider([]))
    with pytest.raises(json.JSONDecodeError):
        cli.main(
            [
                "browse",
                "--url",
                "https://shop.test/",
                "--goal",
                "Search",
                "--uncertainty",
                str(path),
                "--text-model",
            ]
        )
    assert surface.closed == [False]
    assert helper.client.is_closed


def test_desktop_list_and_goal(monkeypatch, capsys):
    import jev_context.act.desktop as desktop

    monkeypatch.setattr(desktop, "list_windows", lambda: [{"title": "Fixture", "pid": 1}])
    assert cli.main(["desktop", "--list"]) == 0
    assert json.loads(capsys.readouterr().out)["windows"][0]["title"] == "Fixture"
    surface = closable(search_flow())
    surface.name = "desktop-test"
    code, packet, _ = run_cli(
        monkeypatch,
        capsys,
        ["desktop", "--window", "Fixture", "--goal", "Search"],
        surface,
        [("CLICK", "Search"), ("DONE",)],
    )
    assert code == 0 and packet["transport"] == "desktop-test"
    with pytest.raises(ValueError, match="goal"):
        cli.main(["desktop", "--window", "Fixture"])


def test_open_desktop_requires_a_target():
    args = cli.argparse.Namespace(window=None, process=None, launch=None)
    with pytest.raises(ValueError, match="--window"):
        cli.open_desktop(args)


def test_extract_structures_a_page_and_selects_records(monkeypatch, capsys):
    from jev_context import analysis

    class Extracting:
        name = "cdp"

        def extract(self, scope=None, limit=500):
            return {
                "url": "https://shop.test/r",
                "title": "R",
                "omitted": 0,
                "records": [
                    {"id": "r1", "kind": "row", "text": "Product: Red Runner | Price: $59"},
                    {"id": "r2", "kind": "row", "text": "Product: Black Parka | Price: $180"},
                ],
            }

        def close(self):
            pass

    monkeypatch.setattr(cli, "open_page", lambda args: Extracting())

    def evaluate(parts, task, workers="auto", spec=None):
        judgments = {
            p["id"]: {
                "status": "OK",
                "decision": "MATCH" if "Red" in p["text"] else "EXCLUDE",
                "answers": {},
            }
            for p in parts
        }
        return judgments, {
            "ok": True,
            "usage": {"input_tokens": 1, "output_tokens": 1},
            "usage_complete": True,
            "requests": 1,
        }

    monkeypatch.setattr(analysis, "evaluate", evaluate)
    code = cli.main(["extract", "--url", "https://shop.test/r", "--task", "Shoes under $100"])
    out = json.loads(capsys.readouterr().out)
    assert code == 0 and out["selected_ids"] == ["r1"] and out["records"] == 2


def test_compact_hides_history_details():
    packet = cli.compact(
        {
            "status": "done",
            "ok": True,
            "history": [
                {
                    "step": 1,
                    "operation": "CLICK",
                    "action": "Go",
                    "page_changed": True,
                    "latency_ms": 5,
                    "text": "x",
                }
            ],
        }
    )
    assert packet["trace"] == [
        {"step": 1, "operation": "CLICK", "action": "Go", "page_changed": True}
    ]


def test_compact_keeps_every_field_a_needs_value_run_skipped():
    packet = cli.compact(
        {
            "status": "needs_value",
            "ok": False,
            "fields": [{"label": "Coupon"}, {"label": "Phone"}],
            "supplied": ["name"],
            "history": [],
        }
    )
    assert packet["fields"] == [{"label": "Coupon"}, {"label": "Phone"}]
    assert packet["supplied"] == ["name"]


# ---------------------------------------------------------------------------------------------
def helper_with(responder):
    return text.TextHelper(
        "https://llm.test/v1", "k", "m", transport=httpx.MockTransport(responder)
    )


def chat(content, status=200):
    return lambda request: httpx.Response(
        status, json={"choices": [{"message": {"content": content}}], "usage": {"prompt_tokens": 3}}
    )


def test_text_helper_returns_only_a_validated_value():
    value, meta = helper_with(chat('{"text": "Zurich"}'))({"goal": "g"})
    assert value == "Zurich" and meta["source"] == "text_model" and meta["model"] == "m"
    value, meta = helper_with(chat('{"text": null}'))({"goal": "g"})
    assert value is None and meta["declined"]
    for bad in ('{"text": "a", "extra": 1}', "not json", '{"text": ""}', '{"text": 5}'):
        with pytest.raises(text.TextHelperError, match="invalid"):
            helper_with(chat(bad))({"goal": "g"})
    with pytest.raises(text.TextHelperError, match="http_500"):
        helper_with(chat("{}", 500))({"goal": "g"})


def test_text_helper_requires_https_and_complete_environment(monkeypatch):
    with pytest.raises(text.TextHelperError, match="https"):
        text.TextHelper("http://llm.test/v1", "k", "m")
    for name in ("JEV_TEXT_BASE_URL", "JEV_TEXT_API_KEY", "JEV_TEXT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert text.from_environment() is None
    monkeypatch.setenv("JEV_TEXT_BASE_URL", "https://llm.test/v1")
    monkeypatch.setenv("JEV_TEXT_API_KEY", "k")
    monkeypatch.setenv("JEV_TEXT_MODEL", "m")
    assert isinstance(text.from_environment(), text.TextHelper)


def test_request_builder_rejects_oversized_choice():
    from jev_context.act import space

    actions = [
        {"id": f"e{i}", "kind": "click", "label": f"B{i}", "role": "button", "node": i}
        for i in range(300)
    ]
    with pytest.raises(ValueError, match="too many"):
        space.build_request(page(actions=actions), "x", [])
    assert space.request_bytes({"a": "é"}) == len('{"a":"é"}'.encode())
    assert SEARCH  # shared fixture import is used
