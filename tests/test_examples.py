"""Published examples and newly portable symbol collection stay executable."""

import json
from pathlib import Path

from jev_context import analysis
from jev_context.symbols import parse_symbols

ROOT = Path(__file__).resolve().parents[1]


def test_contract_examples():
    for name in ("choose", "triage"):
        analysis.validate(
            json.loads((ROOT / "examples" / f"{name}.json").read_text(encoding="utf-8"))
        )


def test_go_receiver_and_function():
    text = "package example\ntype Client struct {}\nfunc (c *Client) Send() bool { return true }\nfunc Open() {}\n"
    found = parse_symbols("example.go", text)
    assert [x["symbol"] for x in found] == ["Client.Send", "Open"]
    assert found[0]["line"] == 3


def test_markdown_relative_links_exist():
    import re

    for p in [*ROOT.glob("*.md"), *ROOT.glob("docs/*.md"), *ROOT.glob("skills/**/*.md")]:
        for target in re.findall(r"\]\(([^)]+)\)", p.read_text(encoding="utf-8")):
            if "://" in target or target.startswith("#"):
                continue
            # A query (?lang=zh) or anchor selects a view of the file; the path must exist.
            assert (p.parent / re.split(r"[?#]", target)[0]).exists(), (p, target)


def test_schema_matches_documented_examples():
    import jsonschema

    schema = json.loads((ROOT / "schemas/analysis.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    for p in (ROOT / "examples").glob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and "mode" in data:
            jsonschema.validate(data, schema)


def test_new_namespace_preserves_legacy_workflow_api():
    from jev_context.batch import run as legacy
    from jev_filter.batch import run as current

    assert current is legacy


def test_english_guides_do_not_mix_translated_body_text():
    import re

    for p in (ROOT / "docs").glob("*.md"):
        if ".zh-CN." in p.name:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if re.search(r"[\u4e00-\u9fff]", line):
                assert "]( " not in line and ("简体中文" in line or "中文使用说明" in line), (
                    p,
                    line,
                )


def test_chinese_guides_keep_localized_links():
    import re

    for p in [ROOT / "README.zh-CN.md", *(ROOT / "docs").glob("*.zh-CN.md")]:
        for label, target in re.findall(
            r"\[([^\]]+)\]\(([^)]+\.md)(?:#[^)]*)?\)", p.read_text(encoding="utf-8")
        ):
            if "://" in target or label == "English":
                continue
            if target.endswith("CHANGELOG.md"):
                continue
            localized = p.parent / target.replace(".md", ".zh-CN.md")
            assert not localized.exists(), (p, target)


def test_agent_quickstart_contracts_plan_without_missing_context(tmp_path):
    import re
    import subprocess
    import sys

    for locale in ("", ".zh-CN"):
        text = (ROOT / f"docs/agent-quickstart{locale}.md").read_text(encoding="utf-8")
        spec = json.loads(re.search(r"```json\n(.*?)\n```", text, re.S)[1])
        records = json.loads(re.search(r"<<'JSON'\n(.*?)\nJSON", text, re.S)[1])
        config = tmp_path / "analysis.json"
        inputs = tmp_path / "records.json"
        config.write_text(json.dumps(spec), encoding="utf-8")
        inputs.write_text(json.dumps(records), encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "jev_filter",
                "query",
                "--input",
                str(inputs),
                "--analysis",
                str(config),
                "--task",
                "Choose Beta JSON",
                "--plan",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        planned = json.loads(result.stdout)
        assert planned["requests"] == 1 and not planned["deferred"]
