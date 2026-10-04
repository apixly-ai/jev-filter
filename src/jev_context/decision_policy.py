"""Pure uncertainty admission for typed answers, shared by analysis and execution.

Thresholds describe the provider's answer statistics, not calibrated correctness or permission.
No inference, caching, collection or mutation occurs here.
"""

import copy

from .validation import number

THRESHOLDS = {"min_confidence", "min_top_probability", "min_margin"}
DEFAULT = {key: 0.0 for key in sorted(THRESHOLDS)}
HOSTED_DEFAULT = {**DEFAULT, "min_top_probability": 0.55, "min_margin": 0.10}


def validate(policy=None, *, questions=None, defaults=None):
    """Validate shared thresholds plus optional per-question overrides."""
    policy = copy.deepcopy({} if policy is None else policy)
    if not isinstance(policy, dict) or set(policy) - (THRESHOLDS | {"questions"}):
        raise ValueError(
            "uncertainty supports min_confidence/min_top_probability/min_margin/questions"
        )

    def check(values):
        if not isinstance(values, dict) or set(values) - THRESHOLDS:
            raise ValueError("question uncertainty supports threshold fields only")
        for key, value in values.items():
            if not number(value):
                raise ValueError(key + " must be a finite number in 0..1")

    check({k: v for k, v in policy.items() if k != "questions"})
    overrides = policy.get("questions", {})
    if not isinstance(overrides, dict):
        raise ValueError("uncertainty.questions must be an object")
    for name, thresholds in overrides.items():
        if (
            not isinstance(name, str)
            or not name
            or (questions is not None and name not in questions)
        ):
            raise ValueError("uncertainty requires a known question")
        check(thresholds)
    return {**DEFAULT, **(defaults or {}), **policy, "questions": overrides}


def assess(answer, question, policy=None):
    """Return explicit review reasons for enabled thresholds, preserving the native answer."""
    policy = policy or DEFAULT
    thresholds = {**DEFAULT, **policy, **policy.get("questions", {}).get(question, {})}
    metrics = {"confidence": answer.get("confidence")}
    reasons = []
    distribution = answer.get("probabilities")
    if answer.get("type") == "noul" and number(answer.get("noul")):
        p = answer["noul"]
        metrics.update(top_probability=max(p, 1 - p), margin=abs(2 * p - 1))
    elif (
        isinstance(distribution, dict)
        and distribution
        and all(number(v) for v in distribution.values())
    ):
        ranked = sorted(distribution.values(), reverse=True)
        metrics.update(
            top_probability=ranked[0], margin=ranked[0] - (ranked[1] if len(ranked) > 1 else 0)
        )
        selected = distribution.get(answer.get("choice"))
        if (
            answer.get("type") == "choice"
            and any(thresholds[key] > 0 for key in THRESHOLDS)
            and number(selected)
            and selected + 1e-12 < ranked[0]
        ):
            reasons.append(
                {
                    "question": question,
                    "reason": "selected_option_not_top",
                    "actual": selected,
                    "top_probability": ranked[0],
                }
            )
    for metric in ("confidence", "top_probability", "margin"):
        threshold = thresholds["min_" + metric]
        if threshold <= 0:
            continue
        actual = metrics.get(metric)
        if not number(actual):
            reasons.append({"question": question, "reason": "missing_" + metric})
        elif actual + 1e-12 < threshold:
            reasons.append(
                {
                    "question": question,
                    "reason": "below_min_" + metric,
                    "actual": actual,
                    "threshold": threshold,
                }
            )
    return reasons
