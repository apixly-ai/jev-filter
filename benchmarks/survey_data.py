"""Deterministic synthetic support tickets with ground truth, for survey e2e tests and benchmarks.

Every record is generated from templates with a fixed seed; the truth labels are the template's
labels, so accuracy is measurable without human annotation. English and Chinese are mixed.
"""

import argparse
import json
import random
from pathlib import Path

PRODUCTS = ["Atlas Router", "Nimbus Cloud Drive", "Pulse Watch", "Orbit Phone", "Kite Tablet"]

TEMPLATES = {
    "billing": [
        "I was charged twice for {product} this month. Please refund the duplicate payment.",
        "My invoice for {product} shows a price that is higher than what I signed up for.",
        "Why did my card get billed again after I already paid for {product}?",
        "{product} 这个月扣了我两次费，请退还重复的款项。",
        "The tax on my {product} receipt looks wrong, can you correct the invoice?",
    ],
    "bug": [
        "{product} crashes every time I open the settings page since the last update.",
        "After the update, {product} keeps disconnecting every few minutes.",
        "The sync button in {product} does nothing and shows error code 0x80.",
        "{product} 升级后一打开设置就闪退。",
        "Battery drains within two hours on {product}, it used to last a whole day.",
    ],
    "feature_request": [
        "It would be great if {product} supported dark mode.",
        "Please add an export to CSV option in {product}.",
        "Could {product} let me schedule tasks for later? That would save me time.",
        "希望 {product} 能增加批量导出功能。",
        "I'd love a keyboard shortcut to switch accounts in {product}.",
    ],
    "account": [
        "I can't log in to my {product} account, the reset email never arrives.",
        "How do I change the email address on my {product} account?",
        "My {product} account was locked after too many attempts, please unlock it.",
        "我的 {product} 账号被锁定了，怎么解锁？",
        "I want to merge two {product} accounts into one.",
    ],
    "shipping": [
        "My {product} order has not arrived and tracking hasn't updated in a week.",
        "The {product} I received was damaged in transit.",
        "Can I change the delivery address for my {product} order?",
        "我订的 {product} 一周了还没发货。",
        "The courier left my {product} at the wrong address.",
    ],
}
TONE = {
    0: [
        "This is unacceptable and I'm furious.",
        "Honestly this is the worst service I've had.",
        "太让人生气了，完全不能接受。",
        "I'm really angry about this.",
    ],
    1: ["", "Thanks.", "Let me know.", "谢谢。"],
    2: [
        "Otherwise I love the product, keep it up!",
        "Thanks, you've always been great.",
        "总体很满意，辛苦了！",
        "Really appreciate your help, the team is fantastic.",
    ],
}
CHURN = [
    "If this isn't fixed I'm going to cancel my subscription.",
    "I'm seriously thinking about switching to a competitor.",
    "不解决的话我就退订了。",
]
SPAM = [
    "Congratulations! You have won a free cruise, click here to claim.",
    "Buy cheap followers now, best prices guaranteed!!!",
    "限时优惠！点击链接领取现金红包。",
    "Earn $5000 a week working from home, no experience needed.",
]


def generate(n, seed=20260930, spam_share=0.1):
    rng = random.Random(seed)
    records = []
    for i in range(n):
        rid = f"t{i + 1:05d}"
        if rng.random() < spam_share:
            records.append(
                {"id": rid, "text": rng.choice(SPAM), "product": "", "truth": {"spam": True}}
            )
            continue
        topic = rng.choice(list(TEMPLATES))
        tone = rng.choices([0, 1, 2], weights=[3, 5, 2])[0]
        churn = tone == 0 and rng.random() < 0.6
        product = rng.choice(PRODUCTS)
        parts = [rng.choice(TEMPLATES[topic]).format(product=product)]
        if TONE[tone]:
            extra = rng.choice(TONE[tone])
            if extra:
                parts.append(extra)
        if churn:
            parts.append(rng.choice(CHURN))
        records.append(
            {
                "id": rid,
                "text": " ".join(parts),
                "product": product,
                "truth": {"spam": False, "topic": topic, "sentiment": tone, "churn": churn},
            }
        )
    return records


SPEC = {
    "task": "Summarise what customers contact support about, how they feel, and churn risk.",
    "keep": ["product"],
    "screen": {
        "instructions": "The record is a genuine customer support request about a product or service (not spam or advertising)."
    },
    "questions": {
        "topic": {
            "type": "choice",
            "instructions": "What is the main topic of this support request?",
            "criteria": {
                "billing": "Charges, refunds, invoices, prices, payments.",
                "bug": "Something in the product is broken, crashes, errors or malfunctions.",
                "feature_request": "Asks for new functionality or an improvement.",
                "account": "Login, password, account settings, locked or merged accounts.",
                "shipping": "Delivery, tracking, damaged or misdelivered orders.",
                "other": "None of the above.",
            },
        },
        "sentiment": {
            "type": "score",
            "instructions": "How does the customer feel?",
            "criteria": [
                "Angry or very frustrated",
                "Neutral or matter-of-fact",
                "Positive or appreciative",
            ],
        },
        "churn": {
            "type": "noul",
            "instructions": "The customer threatens or considers cancelling, leaving or switching to a competitor.",
        },
    },
    "group_by": ["topic", "product"],
    "confidence_floor": 0.6,
    "examples_per_group": 2,
}


def score(records, report_answers):
    """Accuracy of the survey answers against the generated truth."""
    truth = {r["id"]: r["truth"] for r in records}
    stats = {"topic": [0, 0], "sentiment": [0, 0], "churn": [0, 0], "screen": [0, 0]}
    for rid, t in truth.items():
        answers = report_answers.get(rid)
        screened = answers is not None
        stats["screen"][0] += screened == (not t["spam"])
        stats["screen"][1] += 1
        if t["spam"] or not answers:
            continue
        stats["topic"][0] += answers["topic"]["choice"] == t["topic"]
        stats["topic"][1] += 1
        stats["sentiment"][0] += round(answers["sentiment"]["score"]) == t["sentiment"]
        stats["sentiment"][1] += 1
        stats["churn"][0] += (answers["churn"]["noul"] >= 0.5) == t["churn"]
        stats["churn"][1] += 1
    return {
        k: {"correct": c, "total": n, "accuracy": round(c / n, 4) if n else None}
        for k, (c, n) in stats.items()
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument(
        "--out", required=True, help="Directory for records.jsonl, truth.json, spec.json"
    )
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    records = generate(args.n)
    with open(out / "records.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(
                json.dumps({k: v for k, v in r.items() if k != "truth"}, ensure_ascii=False) + "\n"
            )
    (out / "truth.json").write_text(
        json.dumps({r["id"]: r["truth"] for r in records}, ensure_ascii=False), encoding="utf-8"
    )
    (out / "spec.json").write_text(json.dumps(SPEC, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"records": len(records), "out": str(out)}))


if __name__ == "__main__":
    main()
