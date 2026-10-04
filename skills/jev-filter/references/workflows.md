# One read-only entrypoint for maintained skills

Use [`scripts/workflow.py`](https://github.com/apixly-ai/jev-filter/blob/main/skills/jev-filter/scripts/workflow.py) when the skill has collected its own candidate records,
or needs bounded code/change/log evidence. It invokes the installed `jev-filter`
once with literal argv and replaces its own process: native stdout, stdin, exit 2,
signal handling and evidence receipts stay with the canonical runtime. It has no
shell collector, action executor or inference-result cache.

Use Python 3.10+ and the maintained Jev Filter 0.4.1 CLI. Existing programmatic
acquisition, SRE and browser operators already own collection and judgment; reuse
them directly rather than adding this helper around their output.

Set `JEV_SKILL_DIR` to the directory containing this skill, then select a route:

```sh
JEV_SKILL_DIR=/path/to/jev-filter
python "$JEV_SKILL_DIR/scripts/workflow.py" code \
  --root /path/to/workspace --query 'retry after upstream transport failure' \
  --expand-callers --task 'Find transport retries before a response is committed'

python "$JEV_SKILL_DIR/scripts/workflow.py" diff \
  --root /path/to/workspace --base main \
  --task 'Select changes affecting stream truncation'

python "$JEV_SKILL_DIR/scripts/workflow.py" logs \
  --input events.jsonl --group-by request_id \
  --task 'Select CURRENT correlated transport failures' --analysis incident.json
```

`code` requires a pattern or lexical query. A query without a pattern uses its
escaped literal phrase as the exact baseline, then bounded BM25 recall. Caller
expansion is syntactic Python one-hop evidence, not a resolved call graph.
`diff` requires exactly one of `--base`, `--staged`, `--unstaged`; `--head` requires
`--base`. `logs --input -` accepts a program-owned stdin pipeline; sanitize raw
headers, credentials and customer content in the owning collector first.

## Candidate records

Collect `{id,text,...metadata}` once, retaining source/revision privately. Supply
the task, provenance, confirmed facts and positive atomic requirements in an
analysis file. For example:

```json
{
  "model": "jev-1.13.0",
  "contract": {"id": "caller.connection-screen", "version": "1"},
  "context": {"scope": "Current synthetic connection incidents"},
  "required_context": ["scope"],
  "required_record_fields": ["source.source_url", "source.observed_at"],
  "requirements": [
    {"id": "establishment", "statement": "The CURRENT request failed during DNS, TCP or TLS establishment.", "expected": true},
    {"id": "headers", "statement": "The CURRENT request received HTTP response headers.", "expected": false}
  ]
}
```

This is a synthetic incident example, not a ready-made business policy. Reuse a
domain's reviewed criteria and per-object history; model confidence cannot replace
missing facts, identity, permission, delivery or billing evidence.

```sh
python "$JEV_SKILL_DIR/scripts/workflow.py" records \
  --input candidates.json --task 'Find current connection failures' \
  --analysis incident.json --workers 4
```

The default is semantic `filter`, even for short fixtures. Use `--mode analyze` for
caller-defined typed questions, or `choose` for one candidate from a complete set.
`--plan` does no inference. Parse packets on exit 2: keep `selected_ids`,
`review_ids`, `complete`, decisions and receipt refs. Only unresolved originals
need main-model inspection. `status=OK` is not acceptance when the excerpt's
`decision` is REVIEW/EXCLUDE or it carries failed review metrics.

Analysis uncertainty is opt-in. Versioned contracts fingerprint the actual rule
and model, not merely the file name. Preserve native statuses/reasons in downstream
records; label-based rechecking must not promote a reviewed item into a profile.

## Repeated classifications and saved probability evaluation

```sh
python "$JEV_SKILL_DIR/scripts/workflow.py" survey \
  --input records.json --spec survey.json --dry-run
python "$JEV_SKILL_DIR/scripts/workflow.py" survey \
  --input records.json --spec survey.json --labels labels.jsonl --workers 4
python "$JEV_SKILL_DIR/scripts/workflow.py" eval --input labelled-probabilities.json
```

Survey planning is offline. Semantic runs are billable; pass an authorized key
through the established credential mechanism, never argv. Defaults bound workers
to four (maximum 30), survey records to 1,000, planned requests to 30 and estimated
input cost to $0.05; explicit flags may lower or raise those bounded limits.
`eval` consumes saved labelled probabilities with disjoint calibration/holdout
groups and makes no model calls. It reports failures/coverage as well as errors;
it does not fit a calibrator or verify open-ended writing.

## Validation and scope

New integration needs fixed source-bound inputs, expected IDs/dispositions,
baseline/treatment, partial failures, whole requested-operation timing, UTF-8
context bytes and actual per-model usage. Unknown usage remains unknown. A wrapper
parity test establishes routing, not model improvement; a filtering-stage speed
result does not establish whole-agent speed. Public 0.4.1 measurements and negative
results are in the [benchmark guide](https://apixly-ai.github.io/jev-filter/docs/benchmarks.html).

The helper exposes no browser/desktop execution, arbitrary command execution or
customer messaging. Business executors retain ordered actions and verification.
