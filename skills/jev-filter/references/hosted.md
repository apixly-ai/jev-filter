# Hosted execution: building inputs, reading outputs

Covers `browse`, `desktop`, `extract` and `survey`. Each prints one JSON document on stdout
(`survey --format md` prints Markdown). The full history, per-step decision distributions and
per-record answers go to a private archive file (mode 0600, in the system temporary
directory) whose path is in `archive`. Exit code 0 means
complete and ok; 2 means read stdout and act on `status`. Never paste an archive into a public
report.

## browse and desktop

### What to pass

| Piece | Flags | Rule |
|---|---|---|
| Goal | `--goal` | One short outcome that is observable on the surface, with every constraint ("in stock only", "size 42"). No secrets: the goal is sent for inference. |
| Values | `--value KEY=VALUE` (repeatable), `--values FILE` (`-` reads stdin) | Jev cannot write text. It only picks which named value fits a field. |
| Verifier | `--verify-text`, `--verify-url`, `--verify-question` | Pass at least one. Without a verifier, `done` is only the model's opinion. |
| Browser surface | `--url`; or `--cdp-port N [--target-id T]`; or `--transport camofox --session S [--tab T]` | Navigation stays on the start origin unless `--allow-origin URL` or `--any-origin`. |
| Desktop surface | `--window REGEX`, `--process NAME`, `--launch CMD` | Run `desktop --list` first and anchor an exact title: `--window '^Invoice Tool$'`. |
| Budgets | `--max-steps` (60), `--max-decisions` (120) | Short goals; split long tasks and call once per sub-goal. |
| Probe | `--dry-run` | Observe, decide one step, execute nothing; the decision is in `pending`. |

Values file (`--values values.json`):

```json
{
  "query": "red shoes",
  "size": 42,
  "email": {"value": "ada@example.com", "description": "contact email for the order confirmation"},
  "phone": {"value": "+1 555 0100", "sensitive": true, "description": "mobile number for delivery"}
}
```

- A value is a string or number, or an object with a required `value` and optional
  `description` and `sensitive`. Names are nonempty strings. `--value` pairs override the file.
- What Jev sees for each name: the `description` if present, otherwise the value itself, or
  `[sensitive]` for a sensitive value without a description. Add descriptions whenever two
  values could fit the same field (billing versus shipping address).
- `sensitive: true` keeps the typed text out of the trace and the archive (`[sensitive]`).
- Never supply passwords. Password fields are not observed at all; use a pre-authenticated
  browser profile (`--cdp-port`, Camofox) instead.
- `--text-model` lets an OpenAI-compatible model (`JEV_TEXT_BASE_URL`, `JEV_TEXT_API_KEY`,
  `JEV_TEXT_MODEL`) write a value the goal implies, such as a search phrase. It never invents
  personal data; prefer explicit values.

Verifiers run on a fresh observation after the loop stops, and every verifier given must pass:

- `--verify-text`: case-insensitive substring of the final visible text.
- `--verify-url`: a Python regular expression searched in the final URL.
- `--verify-question`: a Jev yes/no question on the final page (passes at probability 0.5 or
  more). It is billable and weaker than text or URL checks.

### What comes back

```json
{
  "status": "needs_confirmation",
  "ok": false,
  "goal": "Buy the cheapest red shoes in size 42",
  "steps": 5,
  "decisions": 6,
  "requests": 6,
  "usage": {"input_tokens": 21480, "output_tokens": 0},
  "final": {"url": "http://127.0.0.1:8000/cart.html", "title": "Cart"},
  "pending": {"id": "e2", "kind": "click", "label": "Place order", "role": "button"},
  "reason": "label_rule",
  "confirm_token": "f25e0c1d9a7b4e21:e2",
  "session": {"cdp_port": 58111, "target_id": "0A92F3"},
  "trace": [
    {"step": 1, "operation": "TYPE_TEXT", "action": "Search", "value_key": "query", "page_changed": true},
    {"step": 2, "operation": "CLICK", "action": "Red Runner", "page_changed": true}
  ],
  "archive": "/tmp/jev-context-8h2k1q.json"
}
```

Keys appear only when they apply. `trace` lists operations and control labels, never typed
text. `verification` holds `{"passed", "text", "url", "question", "question_probability"}` when a
verifier ran. `dialogs` lists JavaScript dialogs that were dismissed.

| `status` | What to do |
|---|---|
| `done` (exit 0) | Goal reported done and every verifier passed. Still check anything that matters yourself. |
| `unverified` | The model said DONE but a verifier failed. Inspect `final` and `verification`; do not report success. |
| `needs_confirmation` | `pending` is irreversible (`reason`: `label_rule` or `jev_probability`). Ask the user. Only after a clear yes, resume with `--confirm TOKEN` on the same session. `confirmation_stale` means the page changed: observe again. |
| `needs_value` | `field` (the field it stopped at) or `fields` (fields it skipped) and `supplied` (names given). Ask the user for the missing value, then rerun. |
| `blocked` | `reason`: `challenge` (CAPTCHA, hand to the user), `login_required` (sign in yourself or use a signed-in profile), `model_blocked`, `no_progress` or `repeating` (narrow the goal). |
| `dry_run` | The decided step is in `pending`; nothing was executed. |
| `origin_blocked` | Navigation left the allowed origins (`origin`). Add `--allow-origin` only if the user expects that site. |
| `budget_exhausted` | Step or decision budget reached (`budget`). Split the goal. |
| `error` | Transport, provider or safety-gate failure (`error`), for example a refused sensitive window or a STOP file. Nothing was retried. |

Resuming a paused browser run (the first run needs `--keep-open` so `session` is returned):

```sh
jev-filter browse --cdp-port 58111 --target-id 0A92F3 --confirm f25e0c1d9a7b4e21:e2 \
  --goal 'Buy the cheapest red shoes in size 42' --verify-text 'order has been placed' --close-browser
```

For Camofox, resume with `--transport camofox --session S --tab <session.camofox_tab>`. The
resumed run executes only the confirmed action, verifies and stops, unless
`--continue-after-confirm`. `--allow-irreversible` disables the gate for a whole run: use it only
when the user has approved every commit the goal implies.

`desktop --list` prints `{"windows": [{"title": …, "pid": …, "class": …}]}` on Windows
(`"process"` instead of `"class"` on macOS).

## extract

```sh
jev-filter extract --url 'https://shop.example/results?q=red' \
  --task 'In-stock shoes under $70' --analysis analysis.json
```

The page becomes records `{id, kind, text, section, caption?, href?}`: `kind` is `row` (table
rows as `Header: value | Header: value`), `heading`, `block` or `link`; ids are the kind's first
letter plus a position (`r3`, `l12`). `--scope CSS` limits collection to one container,
`--max-records` caps it. The records then follow the `query` contract in
[contract.md](contract.md): the same analysis spec, `selected_ids`, `review_ids`, `complete`,
projection and exit codes. Nothing is clicked.

## survey

```sh
jev-filter survey --input tickets.jsonl --spec survey.json --dry-run   # estimate only, free
jev-filter survey --input tickets.jsonl --spec survey.json --labels labels.jsonl
jev-filter survey --input tickets.jsonl --spec survey.json --format md
```

### Input records

`--input` accepts JSONL, a JSON array (or `{"records": [...]}`), CSV, or a directory whose
`.txt`/`.md` files become records; repeat it to combine sources; `-` reads stdin. The text comes
from `text_field` (default `text`) and the id from `id_field` (default `id`; without one the id
is `SOURCE#LINE`).
Fields named in `keep` travel with the record and can be grouped by. Texts longer than
`--max-chars` are cut and counted in `input.truncated_texts`; more than `--max-records`
(200,000) records set `input.truncated` and `complete: false`.

```json
{"id": "T-1042", "text": "Charged twice this month, fix it or I cancel.", "product": "Pro"}
```

### Spec

```json
{
  "task": "What do customers contact support about, how do they feel, and who may churn?",
  "keep": ["product"],
  "context": {"policy": "Refund requests count as billing."},
  "screen": {"instructions": "The record is a genuine support request (not spam).", "threshold": 0.5},
  "questions": {
    "topic": {"type": "choice", "instructions": "Main topic of the request?",
              "criteria": {"billing": "Charges, refunds, invoices", "bug": "Something broken",
                           "shipping": "Delivery and tracking", "other": "Anything else"}},
    "sentiment": {"type": "score", "instructions": "How does the customer feel?",
                  "criteria": ["Angry", "Neutral", "Positive"]},
    "churn": {"type": "noul", "instructions": "The customer threatens to cancel or switch."}
  },
  "group_by": ["topic", "product"],
  "confidence_floor": 0.6,
  "examples_per_group": 3,
  "batch_size": "auto"
}
```

| Field | Rule |
|---|---|
| `task` | Required here or via `--task`. Shared purpose, not a per-record question. |
| `questions` | 1 to 16. `choice`: `criteria` maps option to description (at most 255 options; include an `other`). `score`: 2 to 10 ordered levels. `noul`: a yes/no statement phrased positively. Whole spec at most 16,000 characters. |
| `keep` | Record fields to carry for grouping and excerpts (merged with `--keep`). |
| `context` | Facts that apply to every record. |
| `screen` | Optional relevance pre-pass (one yes/no per record); records below `threshold` (0.5) skip the full questions. Worth it only when most records are irrelevant. |
| `group_by` | Choice question ids or kept fields; each yields a crosstab and representative examples. |
| `confidence_floor` | Answers below it count as uncertain (0 to 1, default 0.6). Uncalibrated until `--labels`. |
| `examples_per_group` | Most confident excerpts per group (3), bounded overall by `--budget-chars`. |
| `batch_size` | `auto` or 1 to 128 records per request. |
| `model`, `usd_per_million_input`, `text_field`, `id_field` | Optional overrides. |

Labels for calibration (`--labels labels.jsonl`), one line per labelled record, any subset of
question ids; choice by option name, score by level index, noul as a boolean:

```json
{"id": "T-1042", "topic": "billing", "sentiment": 0, "churn": true}
```

`--propose-categories QUESTION` replaces that choice question's criteria with categories a text
model proposes from a fixed-seed sample (needs the `JEV_TEXT_*` variables); Jev then classifies
every record into them.

### Report

```json
{
  "ok": true, "complete": true, "task": "…", "records": 10000, "evaluated": 9000,
  "screened_out": 1000, "failed": 0, "failed_ids": [],
  "uncertain_records": 212, "uncertain_ids": ["T-0007"],
  "questions": {
    "topic": {"type": "choice", "answered": 9000, "uncertain": 90,
              "counts": {"billing": 2410}, "share": {"billing": 0.2678}, "mean_confidence": 0.93},
    "sentiment": {"type": "score", "answered": 9000, "uncertain": 110, "mean": 0.84,
                  "levels": {"0": {"label": "Angry", "count": 2950}}},
    "churn": {"type": "noul", "answered": 9000, "uncertain": 40, "yes": 1210,
              "yes_share": 0.1344, "mean_probability": 0.15}
  },
  "crosstabs": {"topic": {"billing": {"n": 2410, "sentiment_mean": 0.41, "churn_yes_share": 0.31}}},
  "representatives": {"topic": {"billing": [{"id": "T-1042", "confidence": 0.99, "excerpt": "…"}]}},
  "usage": {"input_tokens": 5190000, "output_tokens": 0}, "requests": 375,
  "estimated_input_usd": 0.218, "preflight": {"requests": 390, "input_tokens_estimate": 5500000, "input_usd_estimate": 0.231},
  "calibrated": false, "calibration_note": "…", "input": {"rows": 10000, "truncated": false},
  "archive": "/tmp/jev-context-p3v9xa.json"
}
```

- Only `failed_ids` and `uncertain_ids` (at most 50 each) need your attention; do not
  re-classify settled records.
- With `--labels`, `calibration` holds, per question, accuracy, accuracy by confidence band and
  the lowest floor reaching 95% accuracy with at least 20 samples; `calibrated` becomes true.
- `--dry-run` prints `{"ok": true, "dry_run": true, "records", "requests", "deferred",
  "input_tokens_estimate", "input_usd_estimate", "basis", "input"}` and calls nothing. The token
  estimate is UTF-8 bytes / 3, an upper bound.
- Budget refusal (`--max-usd`, default 5; `--max-requests`, default 10,000) prints
  `{"ok": false, "refused": "budget", "estimate": …}` with exit 2 and makes no inference call.
- Jev writes no prose. Write the narrative yourself from the report and cite record ids.
