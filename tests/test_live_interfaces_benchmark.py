from benchmarks import live_interfaces


def test_unknown_interface_usage_is_not_a_zero_bill():
    result = live_interfaces.usage_snapshot({"ok": False})
    assert result["usage_complete"] is False
    assert result["known_usage"] == {"input_tokens": None, "output_tokens": None}
    assert result["requests"] is None


def test_interface_usage_uses_actual_telemetry_and_keeps_unknown_attempts():
    result = live_interfaces.usage_snapshot(
        {
            "telemetry": {
                "usage": {"input_tokens": 57, "output_tokens": 11},
                "usage_complete": False,
                "requests": 2,
                "unknown_usage_attempts": 1,
            }
        }
    )
    assert result["known_usage"] == {"input_tokens": 57, "output_tokens": 11}
    assert result["usage_complete"] is False
    assert result["unknown_usage_attempts"] == 1


def test_public_packet_replaces_machine_paths_without_discarding_decisions():
    result = live_interfaces.public_packet(
        {
            "archive": "/synthetic/private-root/receipt.json",
            "selected_ids": ["sample.py:persist_token:1"],
            "excerpts": [{"source": {"path": "/synthetic/private-root/sample.py"}}],
        }
    )
    assert result["selected_ids"] == ["sample.py:persist_token:1"]
    assert result["excerpts"][0]["source"]["path"] == "sample.py"
    assert result["archive"].startswith("receipt:")


def test_survey_fixture_balanced_labels_and_extract_exact_rule():
    records, labels, expected = live_interfaces.survey_fixture()
    assert len(records) == len(labels) == sum(expected.values()) == 64
    assert expected["billing"] == expected["bug"] == 16
    assert live_interfaces.extract_price_filter(["L1", "L3", "L4", "L7"]) == ["L1", "L4", "L7"]
