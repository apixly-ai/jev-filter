"""Offline contracts for the hosted execution loop. No browser, no paid API."""

import pytest

from jev_context.act import kernel, space
from jev_context.act.browser import StalePage, fingerprint


def page(url="https://shop.test/", text="Search", actions=None, **extra):
    state = {
        "url": url,
        "title": "Shop",
        "text": text,
        "scroll": {"y": 0},
        "actions": actions if actions is not None else [],
        "marker": [url, text, repr(actions)],
        "page_key": [url],
        "guards": {},
        **extra,
    }
    for a in state["actions"]:
        if "node" in a:
            state["guards"][str(a["node"])] = [a["node"], a.get("label"), a.get("value")]
    state["fingerprint"] = fingerprint(state)
    return state


SEARCH = [
    {
        "id": "e1",
        "kind": "fill",
        "label": "Search products",
        "role": "searchbox",
        "value": "",
        "node": 10,
    },
    {
        "id": "e2",
        "kind": "click",
        "label": "Open Search products",
        "role": "searchbox",
        "value": "",
        "node": 10,
    },
    {"id": "e3", "kind": "click", "label": "Search", "role": "button", "node": 20},
    {"id": "wait", "kind": "wait", "label": "Wait for the page to update"},
]


def choice(options, selected, confidence=0.9):
    options = list(options)
    return {
        "type": "choice",
        "choice": selected,
        "confidence": confidence,
        "probabilities": {o: (1.0 if o == selected else 0.0) for o in options},
    }


class Policy:
    """Scripted decider: each entry names the operation, and optionally a target label/value key."""

    def __init__(self, script, irreversible=0.0):
        self.script = list(script)
        self.irreversible = irreversible
        self.bodies = []

    def __call__(self, body):
        self.bodies.append(body)
        if "verified" in body["questions"]:
            return {
                "answers": {"verified": {"type": "noul", "noul": self.verified}},
                "usage": {"input_tokens": 5, "output_tokens": 1},
                "usage_complete": True,
            }
        step = self.script.pop(0)
        operation, label, value_key = (step + (None, None))[:3]
        qs = body["questions"]
        answers = {"operation": choice(qs["operation"]["criteria"], operation)}
        for name, q in qs.items():
            if name.endswith("_target"):
                wanted = next(
                    (
                        k
                        for k, v in q["criteria"].items()
                        if label and v["element"].endswith("] " + label)
                    ),
                    next(iter(q["criteria"])),
                )
                answers[name] = choice(q["criteria"], wanted)
            elif name == "type_value":
                answers[name] = choice(q["criteria"], value_key or "NONE")
            elif name == "irreversible":
                answers[name] = {"type": "noul", "noul": self.irreversible}
        return {
            "answers": answers,
            "usage": {"input_tokens": 100, "output_tokens": 10},
            "usage_complete": True,
        }


class Surface:
    """A tiny state machine standing in for a browser page or desktop window."""

    def __init__(self, pages, transitions):
        self.pages = pages
        self.current = pages[0]
        self.transitions = transitions
        self.executed = []
        self.stale_once = set()

    def observe(self, limit=250, text_limit=6000):
        return self.current

    def fresh(self, state, action=None):
        return state["fingerprint"] == self.current["fingerprint"]

    def settle(self, action):
        pass

    def act(self, action, state, text=None):
        if action["id"] in self.stale_once:
            self.stale_once.discard(action["id"])
            raise StalePage("changed")
        if not self.fresh(state, action):
            raise StalePage("changed")
        self.executed.append((action["id"], text))
        nxt = self.transitions.get((state["url"], action["id"]))
        if nxt is not None:
            self.current = nxt(text) if callable(nxt) else nxt
        return {"executed": action["id"]}


def test_action_space_indexes_nodes_and_isolates_heads():
    actions = SEARCH + [
        {
            "id": "e4",
            "kind": "select",
            "label": "Sort → Price",
            "role": "combobox",
            "value": "price",
            "current_value": "Relevance",
            "node": 30,
        },
        {
            "id": "e5",
            "kind": "select",
            "label": "Sort → Rating",
            "role": "combobox",
            "value": "rating",
            "current_value": "Relevance",
            "node": 30,
        },
    ]
    elements, targets, controls = space.action_space(actions)
    assert [e["index"] for e in elements] == ["1", "2", "3"]
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1" and targets["CLICK"]["1"]["id"] == "e2"
    assert set(targets["SELECT"]) == {"3:1", "3:2"}
    assert set(controls) == {"WAIT"}


def test_request_has_one_head_per_operation_and_hides_sensitive_values():
    values = {"query": "red shoes", "card": {"value": "4111111111111111", "sensitive": True}}
    body, targets, _ = space.build_request(
        page(actions=SEARCH), "Find red shoes", [], values=values
    )
    qs = body["questions"]
    assert set(qs) == {
        "operation",
        "click_target",
        "type_text_target",
        "type_value",
        "irreversible",
    }
    assert set(qs["type_value"]["criteria"]) == {"query", "card", "NONE"}
    assert "4111111111111111" not in str(body)
    assert body["state"]["supplied_values"] == ["card", "query"]


def test_click_cannot_consume_a_text_target():
    body, targets, controls = space.build_request(page(actions=SEARCH), "go", [])
    answers = {
        "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
        "click_target": choice(body["questions"]["click_target"]["criteria"], "2"),
        "type_text_target": choice(body["questions"]["type_text_target"]["criteria"], "1"),
    }
    decision = space.interpret(answers, targets, controls)
    assert decision["action"]["id"] == "e3" and decision["action"]["kind"] == "click"


@pytest.mark.parametrize(
    "label,kind,p,expected",
    [
        ("Place order", "click", 0.0, (True, "label_rule")),
        ("删除账号", "click", 0.0, (True, "label_rule")),
        ("Next page", "click", 0.9, (True, "jev_probability")),
        ("Next page", "click", 0.1, (False, None)),
        ("Send message", "fill", 0.99, (False, None)),
        ("Send weekly report|checkbox", "click", 0.1, (False, None)),
        ("Delete after 30 days|radio", "click", 0.1, (False, None)),
        ("Delete all records|button", "click", 0.0, (True, "label_rule")),
    ],
)
def test_irreversible_floor_and_probability(label, kind, p, expected):
    label, _, role = label.partition("|")
    action = {"kind": kind, "label": label, **({"role": role} if role else {})}
    decision = {"action": action, "irreversible_probability": p}
    assert space.irreversible(decision, 0.5) == expected


def search_flow():
    home = page(actions=SEARCH)
    typed = page(text="Search", actions=[dict(SEARCH[0], value="red shoes"), *SEARCH[1:]])
    results = page(
        url="https://shop.test/results?q=red",
        text="3 results for red shoes",
        actions=[
            {"id": "e1", "kind": "click", "label": "Red Runner", "role": "link", "node": 40},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    )
    transitions = {("https://shop.test/", "e1"): typed, ("https://shop.test/", "e3"): results}
    return Surface([home, typed, results], transitions)


def test_goal_completes_with_supplied_value_and_independent_verification():
    surface = search_flow()
    policy = Policy([("TYPE_TEXT", "Search products", "query"), ("CLICK", "Search"), ("DONE",)])
    policy.verified = 0.95
    run = kernel.Run(
        surface,
        "Search for red shoes",
        decide=policy,
        values={"query": "red shoes"},
        verify_text="results for red shoes",
        verify_question="Are search results shown?",
    )
    result = run.run()
    assert result["status"] == "done" and result["ok"]
    assert surface.executed == [("e1", "red shoes"), ("e3", None)]
    assert [h["value_key"] for h in result["history"] if h["kind"] == "fill"] == ["query"]
    assert result["verification"]["passed"] and result["usage"]["input_tokens"] == 305
    assert result["history"][0]["page_changed"] is True


def test_done_without_evidence_is_unverified():
    surface = search_flow()
    policy = Policy([("DONE",)])
    result = kernel.Run(surface, "Search", decide=policy, verify_text="results for").run()
    assert result["status"] == "unverified" and not result["ok"]


def test_irreversible_click_pauses_and_confirm_token_executes_exactly_that_action():
    checkout = page(
        url="https://shop.test/cart",
        text="Total $40",
        actions=[
            {"id": "e1", "kind": "click", "label": "Place order", "role": "button", "node": 50},
            {"id": "e2", "kind": "click", "label": "Continue shopping", "role": "link", "node": 51},
        ],
    )
    thanks = page(url="https://shop.test/thanks", text="Order confirmed", actions=[])
    surface = Surface([checkout, thanks], {("https://shop.test/cart", "e1"): thanks})
    first = kernel.Run(surface, "Buy the cart", decide=Policy([("CLICK", "Place order")])).run()
    assert first["status"] == "needs_confirmation" and first["reason"] == "label_rule"
    assert surface.executed == [] and first["pending"]["label"] == "Place order"
    second = kernel.Run(
        surface, "Buy the cart", decide=Policy([("DONE",)]), confirm=first["confirm_token"]
    ).run()
    assert surface.executed == [("e1", None)] and second["status"] == "done"


def test_stale_confirm_token_is_rejected():
    checkout = page(
        url="https://shop.test/cart",
        actions=[
            {"id": "e1", "kind": "click", "label": "Place order", "role": "button", "node": 50}
        ],
    )
    surface = Surface([checkout], {})
    result = kernel.Run(surface, "Buy", decide=Policy([]), confirm="deadbeef:e1").run()
    assert result["status"] == "needs_confirmation" and result["reason"] == "confirmation_stale"
    assert surface.executed == []


def test_stale_decision_is_consumed_and_never_double_executed():
    surface = search_flow()
    surface.stale_once.add("e3")
    policy = Policy([("CLICK", "Search"), ("CLICK", "Search"), ("DONE",)])
    result = kernel.Run(surface, "Search", decide=policy).run()
    assert result["stale_decisions"] == 1
    assert surface.executed == [("e3", None)] and result["status"] == "done"


def test_no_progress_blocks_after_three_unchanged_steps():
    still = page(actions=SEARCH)
    surface = Surface([still], {})
    policy = Policy([("CLICK", "Search")] * 3)
    result = kernel.Run(surface, "Search", decide=policy).run()
    assert (
        result["status"] == "blocked" and result["reason"] == "no_progress" and result["steps"] == 3
    )


def test_type_text_without_a_value_stops_for_the_caller():
    surface = search_flow()
    result = kernel.Run(surface, "Search", decide=Policy([("TYPE_TEXT", "Search products")])).run()
    assert result["status"] == "needs_value" and result["field"]["label"] == "Search products"
    assert surface.executed == []


def test_text_helper_fills_when_no_value_matches():
    surface = search_flow()
    calls = []

    def helper(context):
        calls.append(context)
        return "red shoes", {"source": "text_model", "model": "stub"}

    policy = Policy([("TYPE_TEXT", "Search products"), ("DONE",)])
    result = kernel.Run(surface, "Search red shoes", decide=policy, text_helper=helper).run()
    assert (
        surface.executed[0] == ("e1", "red shoes")
        and result["history"][0]["text_source"] == "text_model"
    )
    assert calls[0]["field"]["label"] == "Search products"


def test_navigation_outside_allowed_origins_stops():
    away = page(url="https://evil.test/", actions=SEARCH)
    surface = Surface([away], {})
    result = kernel.Run(
        surface, "x", decide=Policy([]), allowed_origins=["https://shop.test"]
    ).run()
    assert result["status"] == "origin_blocked" and result["origin"] == "https://evil.test"


def test_step_budget_is_enforced():
    pages = [
        page(
            url=f"https://shop.test/{i}",
            actions=[{"id": "e1", "kind": "click", "label": "Next", "role": "link", "node": i}],
        )
        for i in range(5)
    ]
    surface = Surface(pages, {(f"https://shop.test/{i}", "e1"): pages[i + 1] for i in range(4)})
    result = kernel.Run(surface, "x", decide=Policy([("CLICK", "Next")] * 5), max_steps=2).run()
    assert result["status"] == "budget_exhausted" and result["steps"] == 2


def test_sensitive_supplied_value_is_not_archived():
    surface = search_flow()
    policy = Policy([("TYPE_TEXT", "Search products", "secret"), ("DONE",)])
    values = {"secret": {"value": "hunter2", "sensitive": True}}
    result = kernel.Run(surface, "Search", decide=policy, values=values).run()
    assert surface.executed[0] == ("e1", "hunter2")
    assert "hunter2" not in str(result) and result["history"][0]["text"] == "[sensitive]"


def test_weak_terminal_choice_falls_back_to_plausible_operation():
    surface = search_flow()

    class Weak(Policy):
        def __call__(self, body):
            result = super().__call__(body)
            op = result["answers"]["operation"]
            if len(self.bodies) == 1:  # a hesitant BLOCKED with CLICK close behind
                op["choice"] = "BLOCKED"
                op["probabilities"] = {k: 0.0 for k in op["probabilities"]}
                op["probabilities"].update(BLOCKED=0.45, CLICK=0.35, WAIT=0.2)
            return result

    policy = Weak([("CLICK", "Search"), ("DONE",)])
    result = kernel.Run(surface, "Search", decide=policy).run()
    assert result["terminal_overrides"] == 1 and surface.executed == [("e3", None)]
    assert result["status"] == "done"


def test_confident_blocked_still_stops():
    surface = search_flow()
    result = kernel.Run(surface, "Search", decide=Policy([("BLOCKED",)])).run()
    assert result["status"] == "blocked" and result["terminal_overrides"] == 0
