"""The hosted execution loop: observe → Jev chooses → program executes → observe again.

Decisions are consumed before any mutation, so a retry can never double-execute. Executions are
logged before the next observation, so a navigation cannot erase them. DONE is never proof: the
optional verifiers run on a fresh observation after the loop stops.
"""

import hashlib
import json
import re
import time

from . import space
from .browser import ActionFailed, StalePage, origin_of

TERMINAL = (
    "done",
    "blocked",
    "needs_confirmation",
    "needs_value",
    "budget_exhausted",
    "error",
    "unverified",
    "origin_blocked",
)


def confirm_token(page, action):
    raw = json.dumps(
        [page.get("fingerprint"), action.get("id"), action.get("label")], ensure_ascii=False
    )
    return hashlib.sha256(raw.encode()).hexdigest()[:16] + ":" + action["id"]


def describe(action):
    if not action:
        return None
    keep = ("id", "kind", "label", "role", "section", "href", "key")
    return {k: action[k] for k in keep if action.get(k) not in (None, "")}


class Run:
    """One goal on one surface (browser page or desktop window)."""

    def __init__(
        self,
        surface,
        goal,
        *,
        decide,
        values=None,
        max_steps=60,
        max_decisions=120,
        allow_irreversible=False,
        irreversible_threshold=0.5,
        allowed_origins=None,
        text_helper=None,
        model=space.DEFAULT_MODEL,
        observe_limit=250,
        text_limit=6000,
        confirm=None,
        verify_text=None,
        verify_url=None,
        verify_question=None,
        verify_threshold=0.7,
        stall_steps=3,
        continue_after_confirm=False,
        goal_note=True,
        dry_run=False,
        context=None,
        terminal_threshold=0.5,
        fallback_floor=0.15,
        clock=time.perf_counter,
    ):
        if not goal or not goal.strip():
            raise ValueError("A goal is required")
        self.surface = surface
        self.goal = goal.strip()
        self.decide = decide
        self.values = values or {}
        self.max_steps = max_steps
        self.max_decisions = max_decisions
        self.allow_irreversible = allow_irreversible
        self.threshold = irreversible_threshold
        self.allowed = {origin_of(o) if "://" in o else o for o in (allowed_origins or [])}
        # "initial" pins navigation to the origin of the first observation (attached tabs).
        self.text_helper = text_helper
        self.model = model
        self.observe_limit = observe_limit
        self.text_limit = text_limit
        self.confirm = confirm
        self.verify_text = verify_text
        self.verify_url = verify_url
        self.verify_question = verify_question
        self.verify_threshold = verify_threshold
        self.stall_steps = stall_steps
        self.continue_after_confirm = continue_after_confirm
        self.goal_note = goal_note  # False only for the documented ablation benchmark
        self.dry_run = dry_run
        self.terminal_threshold = terminal_threshold
        self.fallback_floor = fallback_floor
        self.overrides = 0
        self.unfillable = {}  # node -> label of fields the run has no value for
        self.visits = {}  # page fingerprint -> times observed after an action
        self.context = context
        self.clock = clock
        self.history = []
        self.decisions = []
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.usage_complete = True
        self.requests = 0
        self.stale = 0
        self.pending_text = None

    # -- helpers -----------------------------------------------------------------------------
    def observe(self):
        return self.surface.observe(limit=self.observe_limit, text_limit=self.text_limit)

    def origin_ok(self, page):
        if not self.allowed or "url" not in page:
            return True
        return origin_of(page["url"]) in self.allowed

    def ask(self, body):
        self.requests += 1
        result = self.decide(body)
        usage = result.get("usage") or {}
        for k in self.usage:
            if isinstance(usage.get(k), int):
                self.usage[k] += usage[k]
        if not result.get("usage_complete", False):
            self.usage_complete = False
        return result

    def elapsed(self):
        return round((self.clock() - self.started) * 1000)

    def finish(self, status, page, **extra):
        verification = None
        if status == "done" and (self.verify_text or self.verify_url or self.verify_question):
            try:
                final = self.observe()
            except StalePage:
                final = page
            verification = self.verify(final)
            page = final
            if not verification["passed"]:
                status = "unverified"
        if self.unfillable and status in ("blocked", "unverified"):
            # The run could not finish and it skipped fields it had no value for: say so.
            status = "needs_value"
            extra.setdefault("fields", [{"label": v} for v in self.unfillable.values()])
            extra.setdefault("supplied", sorted(self.values))
        return {
            "status": status,
            "ok": status == "done",
            "goal": self.goal,
            "steps": len(self.history),
            "decisions": len(self.decisions),
            "stale_decisions": self.stale,
            "terminal_overrides": self.overrides,
            "requests": self.requests,
            "usage": self.usage,
            "usage_complete": self.usage_complete,
            "elapsed_ms": self.elapsed(),
            "final": {k: page.get(k) for k in ("url", "title") if page and page.get(k) is not None},
            "verification": verification,
            "history": self.history,
            **extra,
        }

    def verify(self, page):
        checks = {}
        if self.verify_text:
            checks["text"] = self.verify_text.casefold() in (page.get("text") or "").casefold()
        if self.verify_url:
            checks["url"] = bool(re.search(self.verify_url, page.get("url") or ""))
        if self.verify_question:
            body = {
                "model": self.model,
                "state": {
                    "page": {k: page.get(k) for k in ("url", "title", "text")},
                    "goal": self.goal,
                },
                "questions": {"verified": {"type": "noul", "instructions": self.verify_question}},
            }
            try:
                p = self.ask(body)["answers"]["verified"]["noul"]
                checks["question"] = p >= self.verify_threshold
                checks["question_probability"] = p
            except Exception as error:  # a failed verifier is a failed verification
                checks["question"] = False
                checks["question_error"] = type(error).__name__
        passed = all(v for k, v in checks.items() if k in ("text", "url", "question"))
        return {"passed": passed, **checks}

    def text_for(self, decision, page):
        key = decision.get("value_key")
        if key and key in self.values:
            return space.value_of(self.values, key), {"source": "values", "value_key": key}
        if self.text_helper is not None:
            action = decision["action"]
            context = {
                "goal": self.goal,
                "field": {k: action.get(k) for k in ("label", "role", "section")},
                "page": {"title": page.get("title"), "text": (page.get("text") or "")[:6000]},
                "recent_actions": [
                    {k: h.get(k) for k in ("action", "text")} for h in self.history[-6:]
                ],
            }
            if self.pending_text and self.pending_text[0] == context:
                return self.pending_text[1], self.pending_text[2]
            text, meta = self.text_helper(context)
            self.pending_text = (context, text, meta)
            return text, meta
        return None, None

    # -- loop ----------------------------------------------------------------------------------
    def run(self):
        self.started = self.clock()
        page = self.observe()
        self.visits[page.get("fingerprint")] = 1
        if page.get("challenge"):
            return self.finish("blocked", page, reason="challenge")
        if page.get("scope_missing"):
            return self.finish("error", page, error="scope_missing")
        if self.allowed == {"initial"}:
            self.allowed = {origin_of(page.get("url", ""))}
        if self.confirm:
            result = self.confirmed(page)
            if result is not None:
                return result
            page = self.observe()
            if not self.continue_after_confirm:
                # The user approved one specific action; report it rather than acting further.
                return self.finish("done", page, confirmed=True)
        unchanged = 0
        while True:
            if page.get("challenge"):
                return self.finish("blocked", page, reason="challenge")
            if not self.origin_ok(page):
                return self.finish("origin_blocked", page, origin=origin_of(page.get("url", "")))
            if len(self.decisions) >= self.max_decisions:
                return self.finish("budget_exhausted", page, budget="decisions")
            if len(self.history) >= self.max_steps:
                return self.finish("budget_exhausted", page, budget="steps")
            try:
                offered = page
                if self.unfillable:
                    offered = dict(
                        page,
                        actions=[
                            a
                            for a in page["actions"]
                            if not (a.get("kind") == "fill" and a.get("node") in self.unfillable)
                        ],
                    )
                body, targets, controls = space.build_request(
                    offered,
                    self.goal,
                    self.history,
                    values=self.values,
                    model=self.model,
                    context=self.context,
                    note=(space.AUTHORIZED_NOTE if self.allow_irreversible else space.GATED_NOTE)
                    if self.goal_note
                    else None,
                )
            except ValueError as error:
                return self.finish("error", page, error=str(error))
            started = self.clock()
            try:
                result = self.ask(body)
            except Exception as error:
                return self.finish("error", page, error=type(error).__name__)
            decision = space.interpret(result["answers"], targets, controls)
            decision = self.gate_terminal(decision, result["answers"], targets, controls)
            decision.update(
                latency_ms=round((self.clock() - started) * 1000), fingerprint=page["fingerprint"]
            )
            self.decisions.append(
                {k: v for k, v in decision.items() if k != "action"}
                | {"action": describe(decision.get("action"))}
            )
            operation = decision["operation"]
            if operation in ("DONE", "BLOCKED"):
                if not self.surface.fresh(page):
                    self.stale += 1
                    page = self.observe()
                    continue
                extra = {"last_confidence": decision["confidence"]}
                if operation == "BLOCKED":
                    extra["reason"] = self.blocked_reason(page)
                return self.finish("done" if operation == "DONE" else "blocked", page, **extra)
            action = decision["action"]
            if self.dry_run:
                return self.finish(
                    "dry_run",
                    page,
                    pending=describe(action),
                    operation=operation,
                    confidence=decision["confidence"],
                    target_probability=decision.get("target_probability"),
                    irreversible_probability=decision.get("irreversible_probability"),
                )
            risky, reason = space.irreversible(decision, self.threshold)
            if risky and not self.allow_irreversible:
                return self.finish(
                    "needs_confirmation",
                    page,
                    pending=describe(action),
                    reason=reason,
                    irreversible_probability=decision.get("irreversible_probability"),
                    confirm_token=confirm_token(page, action),
                )
            text, text_meta = (None, None)
            if action["kind"] == "fill":
                if not self.surface.fresh(page, action):
                    self.stale += 1
                    page = self.observe()
                    continue
                text, text_meta = self.text_for(decision, page)
                if text is None:
                    if action["node"] in self.unfillable or len(self.unfillable) >= 8:
                        return self.finish(
                            "needs_value",
                            page,
                            field=describe(action),
                            supplied=sorted(self.values),
                        )
                    # No supplied value fits: skip this field once and let the next decision
                    # choose among the remaining operations (it may be optional).
                    self.unfillable[action["node"]] = action.get("label")
                    self.history.append(
                        {
                            "step": len(self.history) + 1,
                            "action": action.get("label"),
                            "kind": "fill",
                            "operation": "TYPE_TEXT",
                            "result": "skipped: no supplied value",
                            "skipped": True,
                            "page_changed": False,
                            "url": page.get("url"),
                            "elapsed_ms": self.elapsed(),
                        }
                    )
                    continue
            step = self.execute(page, action, decision, text, text_meta)
            if step is None:
                page = self.observe()
                continue
            if step.get("error"):
                return self.finish("error", page, error=step["error"])
            before = page["fingerprint"]
            self.surface.settle(action)
            try:
                page = self.observe()
            except StalePage:
                time.sleep(0.2)
                page = self.observe()
            changed = page["fingerprint"] != before
            if changed:  # unchanged pages are the stall detector's business
                self.visits[page["fingerprint"]] = self.visits.get(page["fingerprint"], 0) + 1
            self.history[-1]["page_changed"] = changed
            unchanged = 0 if changed or action["kind"] == "wait" else unchanged + 1
            if unchanged >= self.stall_steps:
                return self.finish("blocked", page, reason="no_progress")
            if self.repeating():
                return self.finish("blocked", page, reason="repeating")

    @staticmethod
    def blocked_reason(page):
        if page.get("challenge"):
            return "challenge"  # CAPTCHA / bot check: hand back, never solve
        if page.get("password_fields"):
            return "login_required"  # passwords are never filled; use a signed-in profile
        return "model_blocked"

    def repeating(self, limit=3):
        """A page state revisited `limit` times means the run is cycling (open/close,
        toggle/untoggle). Pagination and scrolling reach new states and are unaffected."""
        return any(count >= limit for count in self.visits.values())

    def gate_terminal(self, decision, answers, targets, controls):
        """A weak DONE/BLOCKED does not end the run when a concrete operation is plausible."""
        probs = decision["operation_probabilities"]
        operation = decision["operation"]
        if operation not in ("DONE", "BLOCKED") or probs[operation] >= self.terminal_threshold:
            return decision
        alternatives = [(p, op) for op, p in probs.items() if op not in ("DONE", "BLOCKED")]
        if not alternatives:
            return decision
        p, op = max(alternatives)
        if p < self.fallback_floor:
            return decision
        forced = dict(answers)
        forced["operation"] = dict(answers["operation"], choice=op)
        replacement = space.interpret(forced, targets, controls)
        replacement["overrode"] = {"operation": operation, "probability": probs[operation]}
        self.overrides += 1
        return replacement

    def execute(self, page, action, decision, text, text_meta):
        try:
            record = self.surface.act(action, page, text=text)
        except StalePage:
            self.stale += 1
            return None
        except ActionFailed as error:
            return {"error": str(error)}
        self.pending_text = None
        entry = {
            "step": len(self.history) + 1,
            "action": action.get("label"),
            "kind": action["kind"],
            "operation": decision["operation"],
            "target": decision.get("target"),
            "confidence": decision.get("confidence"),
            "target_probability": decision.get("target_probability"),
            "irreversible_probability": decision.get("irreversible_probability"),
            "latency_ms": decision.get("latency_ms"),
            "url": page.get("url"),
            "elapsed_ms": self.elapsed(),
            **{k: v for k, v in (record or {}).items() if k != "executed"},
        }
        if text is not None:
            entry["value_key"] = (text_meta or {}).get("value_key")
            entry["text_source"] = (text_meta or {}).get("source")
            sensitive = (
                decision.get("value_key")
                and isinstance(self.values.get(decision["value_key"]), dict)
                and self.values[decision["value_key"]].get("sensitive")
            )
            entry["text"] = "[sensitive]" if sensitive or action.get("sensitive") else text[:200]
        self.history.append(entry)
        return entry

    def confirmed(self, page):
        """Execute exactly the action a previous run paused on, if the page still matches."""
        token = self.confirm
        action_id = token.split(":", 1)[-1]
        action = next((a for a in page.get("actions", []) if a.get("id") == action_id), None)
        if action is None or confirm_token(page, action) != token:
            return self.finish(
                "needs_confirmation", page, reason="confirmation_stale", pending=describe(action)
            )
        decision = {"operation": "CONFIRMED", "action": action, "confidence": None}
        step = self.execute(page, action, decision, None, None)
        if step is None:
            return self.finish(
                "needs_confirmation", page, reason="confirmation_stale", pending=describe(action)
            )
        if step.get("error"):
            return self.finish("error", page, error=step["error"])
        self.surface.settle(action)
        return None
