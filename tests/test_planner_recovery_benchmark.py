"""A reference primary planner cannot bypass observed-action or permission gates."""

import copy
import json

import pytest

from benchmarks.live_planner_recovery import (
    continuation_reason,
    planner_receipt,
    planner_schema,
    recover_once,
)
from jev_context.act.kernel import Run


class Surface:
    def __init__(self, label="Search", kind="click"):
        self.page = {
            "url": "http://127.0.0.1:8000/index.html",
            "fingerprint": "observed",
            "title": "Synthetic fixture",
            "text": "Synthetic fixture",
            "actions": [{"id": "observed-one", "node": 1, "label": label, "kind": kind}],
        }
        self.executed = []
        self.observations = 0
        self.changed = False
        self.fresh_target = True

    def observe(self, **_):
        self.observations += 1
        page = copy.deepcopy(self.page)
        if self.changed and self.observations > 1:
            page["fingerprint"] = "changed"
        return page

    def fresh(self, _page, _action=None):
        return self.fresh_target

    def act(self, action, _page, text=None):
        self.executed.append((action["id"], text))
        return {"executed": action["id"]}

    def settle(self, _):
        pass


def safe_risk(_):
    return {
        "answers": {"irreversible": {"type": "noul", "noul": 0.01}},
        "usage": {"input_tokens": 5, "output_tokens": 1},
        "usage_complete": True,
    }


def make_run(surface=None, decide=safe_risk):
    surface = surface or Surface()
    run = Run(
        surface,
        "Search for red shoes",
        decide=decide,
        values={"query": "red shoes"},
        allowed_origins=["http://127.0.0.1:8000"],
        max_steps=3,
        max_decisions=4,
    )
    run.started = run.clock()
    return run


def choose(action="observed-one", value="NONE"):
    return lambda _context, _schema: {"action_id": action, "value_ref": value}


def test_schema_only_exposes_observed_ids_and_program_value_references():
    run = make_run()
    schema = planner_schema(run.surface.page, run.values)
    assert schema["properties"]["action_id"]["enum"] == ["observed-one", "NONE"]
    assert schema["properties"]["value_ref"]["enum"] == ["query", "NONE"]
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize(
    "proposal",
    [
        {"action_id": "#invented-selector", "value_ref": "NONE"},
        {"action_id": "observed-one", "value_ref": "invented-text"},
        {"action_id": "observed-one", "value_ref": "NONE", "command": "invented"},
    ],
)
def test_unobserved_or_generated_values_never_reach_execution(proposal):
    run = make_run()
    result = recover_once(run, lambda *_: proposal)
    assert result["status"] == "needs_review"
    assert run.surface.executed == []
    assert run.requests == 0


@pytest.mark.parametrize("label", ["Place order", "Remove Red Runner", "Send message"])
def test_irreversible_label_floor_still_requires_confirmation(label):
    run = make_run(Surface(label=label))
    result = recover_once(run, choose())
    assert result["status"] == "needs_confirmation"
    assert result["reason"] == "label_rule"
    assert run.surface.executed == []
    assert run.requests == 0


def test_unknown_risk_is_review_and_preserves_unknown_usage():
    def unknown(_):
        raise RuntimeError("synthetic unavailable provider")

    run = make_run(decide=unknown)
    result = recover_once(run, choose())
    assert result["status"] == "needs_review"
    assert result["reason"] == "recovery_risk_unknown"
    assert run.surface.executed == []
    assert run.usage_complete is False
    assert run.unknown_usage_attempts == 1


def test_high_typed_risk_cannot_be_overridden_by_primary_choice():
    def risky(body):
        return {**safe_risk(body), "answers": {"irreversible": {"type": "noul", "noul": 0.9}}}

    run = make_run(decide=risky)
    result = recover_once(run, choose())
    assert result["status"] == "needs_confirmation"
    assert run.surface.executed == []


@pytest.mark.parametrize("change", ["fingerprint", "target", "origin", "challenge", "scope"])
def test_freshness_origin_challenge_and_scope_gates_prevent_execution(change):
    run = make_run()
    if change == "fingerprint":
        run.surface.changed = True
    elif change == "target":
        run.surface.fresh_target = False
    elif change == "origin":
        run.surface.page["url"] = "https://unapproved.test"
    elif change == "challenge":
        run.surface.page["challenge"] = True
    else:
        run.surface.page["scope_missing"] = True
    result = recover_once(run, choose())
    assert result["status"] != "resumed"
    assert run.surface.executed == []


def test_fill_uses_only_existing_program_value_and_keeps_cumulative_budget():
    run = make_run(Surface(kind="fill", label="Search products"))
    run.history.append({"action": "Earlier step"})
    run.decisions.append({"operation": "Earlier decision"})
    result = recover_once(run, choose(value="query"))
    assert result["status"] == "resumed"
    assert run.surface.executed == [("observed-one", "red shoes")]
    assert len(run.history) == 2
    assert len(run.decisions) == 2
    assert run.requests == 1
    assert run.usage == {"input_tokens": 5, "output_tokens": 1}


def test_exhausted_decision_budget_cannot_be_reset_by_recovery():
    run = make_run()
    run.decisions = [{"operation": "Earlier"}] * run.max_decisions
    result = recover_once(run, choose())
    assert result["status"] == "budget_exhausted"
    assert run.surface.executed == []
    assert run.requests == 0


def test_primary_tool_start_invalidates_even_a_structured_final_answer():
    lines = [
        json.dumps({"type": "item.started", "item": {"id": "tool", "type": "command_execution"}}),
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "id": "answer",
                    "type": "agent_message",
                    "text": '{"action_id":"observed-one","value_ref":"NONE"}',
                },
            }
        ),
        json.dumps(
            {
                "type": "turn.completed",
                "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1},
            }
        ),
    ]
    result = planner_receipt(lines)
    assert result["proposal"] is None
    assert result["tool_items"] == 1
    assert result["usage_complete"] is True


def test_independent_rejection_of_done_requests_continuation_without_claiming_success():
    result = {"status": "done"}
    assert continuation_reason(result, {"cart": True, "final_gate": False}, 0) == "rejected_done"
    assert continuation_reason(result, {"cart": True, "final_gate": True}, 0) is None


def test_verifier_feedback_never_overrides_confirmation_or_observed_wrong_action():
    assert continuation_reason({"status": "needs_confirmation"}, {"cart": False}, 0) is None
    assert continuation_reason({"status": "done"}, {"cart": False}, 1) is None


def test_grounded_unmet_checks_are_supplied_as_program_verification_facts():
    run = make_run()
    captured = {}

    def plan(context, _schema):
        captured.update(context)
        return {"action_id": "NONE", "value_ref": "NONE"}

    facts = {"checks": {"cart": True, "final_gate": False}, "required_pending_label": "Place order"}
    result = recover_once(run, plan, verification_facts=facts)
    assert captured["program_verification"] == facts
    assert result["status"] == "needs_review"
    assert run.surface.executed == []
