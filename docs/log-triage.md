# Triage correlated logs without mistaking recovered failures for incidents

[简体中文](log-triage.zh-CN.md)

Jev Filter's `triage` groups JSON or JSONL events by a correlation field, preserves
observed event order within each group, and judges the resulting request histories
against typed conditions. It returns matching and review IDs while retaining the
collected evidence. The semantic label does not prove a live incident, recovery or
root cause.

This tutorial finds **current DNS/TCP/TLS establishment failures that have not
received HTTP response headers**. A previous timeout followed by a successful
current attempt must be excluded. Unknown phases remain reviewable. The input is
five fixed synthetic events forming four histories; expected dispositions are
handwritten teaching labels, not a new measured result.

## Keep collection, judgment and verification separate

```text
bounded log collection → request histories → Jev conditions → compact packet
                                                               ↓
                                           live/native verification and diagnosis
```

Your existing log query should own time bounds, service/tenant scope and correlation
identity. Use exact filters for known request IDs or status fields. Jev is useful
when many histories require the same semantic distinction across messages, phases
and attempts. A small exact lookup usually needs no model.

## Install and inspect the fixed history

The npm CLI requires Node.js 22+ on macOS or Linux. Windows can use WSL or the
[Python source install](getting-started.md#python-library-source-install).

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
git clone https://github.com/apixly-ai/jev-filter.git
cd jev-filter
```

`doctor` is offline. The semantic command below needs your own Typesafe API key and
is billable; configure it with the [key guide](getting-started.md#configure-your-key).
No real customer log or credential is required for the tutorial.

The repository's [events.jsonl](../examples/search-filtering/events.jsonl) records
`request_id`, `attempt`, `status`, a message and, when known, the failure phase and
whether response headers arrived. The fixture defines the largest attempt number
as the current attempt within a request. Its order is already the collector's
observed order; `triage` does not reconstruct a missing timeline.

| Request | Supplied evidence | Expected disposition |
|---|---|---|
| `current-tls` | Current TLS failure before HTTP headers | Match |
| `recovered` | Earlier TCP failure; current attempt has HTTP 200 and a valid body | Exclude |
| `current-http` | Current HTTP 503 with response headers | Exclude |
| `unknown-phase` | Failure without phase or header evidence | Review |

The collector produces IDs such as `correlated:current-tls`. It keeps interleaved
events together and preserves each group's observed order. Only consecutive exact
duplicates are coalesced, with multiplicity retained. Malformed rows remain visible
as collection/review issues rather than disappearing.

## Give Jev the scope and atomic conditions

[log-analysis.json](../examples/search-filtering/log-analysis.json) defines the
current-attempt rule, the required shared context, success criteria and exclusions.
Each grouped record must have `source.event_count`. The original per-event facts
stay inside its retained history rather than being copied into shared context.

The contract has two positive atomic statements:

1. The current attempt fails during DNS, TCP or TLS establishment: expected **true**.
2. The current attempt received HTTP response headers: expected **false**.

This expresses both inclusion and exclusion explicitly. An HTTP 503 is a failed
request but is not a pre-response establishment failure. The word “timeout” in an
older attempt is not evidence that the current attempt still fails. Missing phase
information must not be guessed from an error label alone.

Run the opt-in semantic operation from the repository root:

```sh
jev-filter triage --input examples/search-filtering/events.jsonl \
  --group-by request_id \
  --analysis examples/search-filtering/log-analysis.json \
  --task 'Find current unresolved DNS/TCP/TLS failures before HTTP response headers' \
  > triage-result.json
```

The expected match is `correlated:current-tls`; the expected review is
`correlated:unknown-phase`. `correlated:recovered` and `correlated:current-http`
should be excluded. These are fixture expectations to compare with your actual
output, not promised semantic results.

`triage` currently has no `--plan` flag. In a source checkout installed in a virtual
environment with `.[code,dev]`, `python examples/search-filtering/verify.py` validates
grouping, contract admission and planning without inference. It does not measure
classification quality.

## Keep partial results usable and originals recoverable

Parse `selected_ids`, `review_ids`, `complete` and `telemetry.usage_complete`.
This fixture expects an unresolved history, so a semantic run may return exit **2**
with useful JSON. Keep that stdout and the unknown item. Exit 0 is completed
processing, not verified recovery; exit 1 indicates invalid input, setup or
execution failure. Shared missing context returns `NEEDS_CONTEXT`.
See the [CLI contract](cli.md) and [context contract](context-contract.md).

Copy the returned `archive` path to recover a grouped history:

```sh
jev-filter list ARCHIVE_PATH
jev-filter read ARCHIVE_PATH --id correlated:current-tls
```

The triage collector redacts common credential patterns in grouped evidence. It
also retains the raw input in a separate owner-only archive referenced in local
archive/receipt metadata. That raw copy can contain original secrets; redaction is
not an exhaustive privacy guarantee. Keep archives local and share only inspected,
permitted evidence. Local storage is evidence retention, not an inference cache.

## Verify the current system before acting

Use native monitoring or a read-only current-state query to check that the request
identity, attempt and failure are still relevant. Confirm live delivery or recovery
through the application's real success criteria. Jev's history classification
neither restarts services nor establishes a cause. A log window missing the last
successful attempt cannot prove an incident is unresolved; widen or repair
collection and retain uncertainty.

Before production use, compare a fixed labeled sample with your native baseline:
false incidents, missed incidents, reviews, collection failures, returned context,
whole-operation latency and actual usage by model. The
[published benchmarks](benchmarks.md) report both context reductions and slower or
higher-cost cases. Unknown usage remains unknown, not zero. Continue with
[RAG result filtering](search-result-filtering.md) or
[semantic code search](semantic-code-search.md).
