"""Reproduce researched policy/collection gaps offline with synthetic inputs.

Run from the repository root with the project virtual environment:
    .venv/bin/python docs/research/2026-10-04/check_gaps.py

No API calls, browser, credentials, or external actions. This is a behavior
observation, not a quality or performance A/B benchmark.
"""

import json
import tempfile
from pathlib import Path

from jev_context import analysis, tools, validation
from jev_context.act import kernel
from jev_context.act.browser import fingerprint
from jev_context.provider import ProviderError


def choice(criteria, selected, probabilities=None):
    probabilities = probabilities or {k: float(k == selected) for k in criteria}
    count = len(criteria)
    confidence = (max(probabilities.values()) - 1 / count) / (1 - 1 / count) if count > 1 else 1.0
    return {
        "type": "choice",
        "choice": selected,
        "probabilities": probabilities,
        "confidence": confidence,
    }


def requirement_observation():
    spec = analysis.validate(
        {
            "requirements": [
                {"id": "relevant", "statement": "The record is relevant.", "expected": True}
            ]
        }
    )
    answer = choice(
        spec["questions"]["relevant"]["criteria"],
        "SUPPORTED",
        {"SUPPORTED": 0.36, "CONTRADICTED": 0.33, "UNKNOWN": 0.31},
    )
    response = {
        "model": "jev-1.13.0",
        "answers": {"relevant": answer},
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }
    body = {"model": response["model"], "state": "Synthetic record", "questions": spec["questions"]}
    validation.validate_request(body)
    validation.validate_response(body, response)
    decision = analysis.decision(
        {"status": "OK", "answers": response["answers"]}, spec, {"text": "Synthetic record"}
    )
    return {
        "response_valid": True,
        "top_probability": 0.36,
        "runner_up_probability": 0.33,
        "confidence": round(answer["confidence"], 4),
        "observed_decision": decision,
    }


def state(text, actions):
    page = {
        "url": "https://fixture.test/",
        "title": "Synthetic navigation",
        "text": text,
        "scroll": {"y": 0},
        "actions": actions,
        "page_key": ["https://fixture.test/"],
        "marker": [text],
        "guards": {},
    }
    page["fingerprint"] = fingerprint(page)
    return page


class Surface:
    def __init__(self):
        self.current = state(
            "Navigation",
            [
                {"id": "help", "kind": "click", "node": 1, "label": "Help", "role": "button"},
                {"id": "about", "kind": "click", "node": 2, "label": "About", "role": "button"},
            ],
        )
        self.executed = []

    def observe(self, **_kwargs):
        return self.current

    def fresh(self, page, _action=None):
        return page["fingerprint"] == self.current["fingerprint"]

    def settle(self, _action):
        pass

    def act(self, action, _page, text=None):
        self.executed.append(action["id"])
        self.current = state("Opened help center", [])
        return {"executed": action["id"]}


def hosted_observation():
    surface = Surface()
    calls = 0

    def decide(body):
        nonlocal calls
        calls += 1
        answers = {}
        for name, question in body["questions"].items():
            if name == "operation":
                answers[name] = choice(question["criteria"], "CLICK" if calls == 1 else "DONE")
            elif name == "click_target":
                answers[name] = choice(question["criteria"], "1", {"1": 0.51, "2": 0.49})
            elif name == "irreversible":
                answers[name] = {"type": "noul", "noul": 0.0}
        result = {
            "model": body["model"],
            "answers": answers,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "usage_complete": True,
        }
        validation.validate_request(body)
        validation.validate_response(body, result)
        return result

    result = kernel.Run(
        surface, "Open help center", decide=decide, verify_text="Opened help center"
    ).run()
    return {
        "target_probability": 0.51,
        "runner_up_probability": 0.49,
        "target_confidence": 0.02,
        "executed": surface.executed,
        "status": result["status"],
        "verification": result["verification"],
        "note": "The action is reversible and verified; this only demonstrates the absent uncertainty gate.",
    }


def collection_observation():
    with tempfile.TemporaryDirectory(prefix="jev-research-fixture-") as directory:
        source = Path(directory) / "quota.py"
        source.write_text("def consume_quota(balance, amount):\n    return balance - amount\n")
        absent, absent_meta = tools.collect_code(directory, "billing|invoice")
        present, present_meta = tools.collect_code(directory, "consume_quota")
        return {
            "nonmatching_lexical_query_records": len(absent),
            "exact_symbol_query_records": len(present),
            "collection_ok": absent_meta["ok"] and present_meta["ok"],
            "scope": absent_meta["scope"],
            "note": "Documented lexical scope limitation; this is not a measured semantic recall rate.",
        }


def failed_usage_observation():
    def decide(_body):
        raise ProviderError("transport_failed_usage_unknown")

    result = kernel.Run(Surface(), "Open help center", decide=decide).run()
    return {
        "injected_error": "transport_failed_usage_unknown",
        "status": result["status"],
        "reported_error": result["error"],
        "reported_usage": result["usage"],
        "reported_usage_complete": result["usage_complete"],
        "executed_steps": result["steps"],
        "note": "Synthetic transport failure: actual provider usage is unknown, not measured zero.",
    }


if __name__ == "__main__":
    print(
        json.dumps(
            {
                "kind": "offline_behavior_observation",
                "live_inference": False,
                "requirements": requirement_observation(),
                "hosted_target": hosted_observation(),
                "code_collection": collection_observation(),
                "failed_usage": failed_usage_observation(),
            },
            indent=2,
        )
    )
