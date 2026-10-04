# Add semantic code search to an AI coding agent

[简体中文](semantic-code-search.zh-CN.md)

Jev Filter's `code-search` uses a lexical query to collect code candidates, expands
hits to complete functions or methods, then applies typed semantic conditions.
An AI coding agent receives selected source IDs and bounded evidence instead of
every matching line. Originals stay recoverable, and source revisions are checked
before matches return.

This tutorial finds **functions that retry a transient timeout with bounded attempts
and a wait between attempts**. Its three synthetic Python functions include a real
retry loop and two keyword distractors. The expected labels are examples to inspect,
not a new measured result. Search does not execute the candidate code.

## Why search whole functions?

An `rg` hit for `retry` might be an implementation, a log message or a comment. A
complete function can expose control flow, the exception type, an attempt bound and
the actual delay. The collection step supplies these observed symbols to Jev;
Jev determines whether the supplied function meets each declared condition.

```text
rg shortlist → complete symbols → typed conditions → compact evidence → native review
```

If you already know the exact function, path or line, use `rg` or a language server
directly. Semantic filtering is useful when a shortlist has many behaviorally
different matches. It cannot recover an implementation absent from that shortlist.

## Install and inspect the candidates

The npm CLI requires Node.js 22+ on macOS or Linux; Windows can use WSL or the
[Python source install](getting-started.md#python-library-source-install).

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
git clone https://github.com/apixly-ai/jev-filter.git
cd jev-filter
rg -n 'retry|backoff|TimeoutError' examples/search-filtering/code.py
```

`doctor` and `rg` do not perform model inference. The later semantic call requires
your own Typesafe API key and is billable; use the [key guide](getting-started.md#configure-your-key).
The native npm package includes its runtime and code parsers. Python/source users
need a virtual environment, the `code` extra and separately installed ripgrep.

The fixed [code.py](../examples/search-filtering/code.py) contains:

| Symbol | Observed behavior | Expected disposition |
|---|---|---|
| `retry_timeouts` | Catches `TimeoutError`, tries again, waits, stops at a bound | Match |
| `report_timeout` | Writes a message mentioning a timeout and retry | Exclude |
| `run_once` | Handles a timeout after a single invocation | Exclude |

## State the behavior as separate conditions

[code-analysis.json](../examples/search-filtering/code-analysis.json) declares the
goal, the fixed scope and exclusions. It requires observed `symbol`, `path` and
`source_sha256` metadata. Its three atomic statements ask whether the function
invokes the operation again after `TimeoutError`, bounds attempts, and waits
between failures. These are judgments about the supplied function, not
claims about its behavior in an unseen production environment.

Run the opt-in semantic call from the repository root:

```sh
jev-filter code-search 'retry|backoff|TimeoutError' \
  --root examples/search-filtering/code.py \
  --analysis examples/search-filtering/code-analysis.json \
  --task 'Find functions retrying TimeoutError with bounded attempts and backoff' \
  > code-result.json
```

The expected selected source ID is `code.py:retry_timeouts:4` for this fixed file.
Line numbers are part of the observed identity, so use the IDs in your actual result
after editing or replacing the fixture. The other two functions are expected known
mismatches. A missing parser or changed source must remain visible for review.

Unlike `query`, `code-search` currently has no `--plan` flag. To validate the shipped
fixture's collection and contracts without inference, run
`python examples/search-filtering/verify.py` in a source checkout installed with
`.[code,dev]`. That check does not establish semantic accuracy.

## Broaden recall deliberately

For a larger repository, `--query` adds bounded lexical/BM25 recall, and
`--expand-callers` adds one-hop Python syntactic caller clues:

```sh
jev-filter code-search 'retry|backoff|TimeoutError' \
  --root examples/search-filtering/code.py \
  --query 'transient timeout repeated attempts delay' \
  --expand-callers --max-files 2000 \
  --analysis examples/search-filtering/code-analysis.json \
  --task 'Find functions retrying TimeoutError with bounded attempts and backoff'
```

This second command is also billable and only demonstrates the flags; the tiny
fixture does not measure a recall gain. These controls broaden candidate collection,
not exhaustive semantic indexing. Ignore rules, file/candidate limits, unsupported
syntax and missing lexical overlap can still cause misses. A caller clue does not
resolve dynamic dispatch. The [code A/B in the benchmarks](benchmarks.md#record-workflows-better-selection-comes-with-more-work)
reports a deliberately missed no-overlap case even after recall expansion.

## Verify before making a change

Read `selected_ids`, `review_ids`, `complete` and collection issues together. Exit
**2** indicates a partial or unresolved packet; parse its stdout instead of treating
it as no matches. A capped search cannot prove no matching implementation exists.
Shared missing context returns `NEEDS_CONTEXT`; incomplete record facts require
review. [Full CLI behavior](cli.md).

Copy the returned `archive` path to inspect the supplied full function:

```sh
jev-filter list ARCHIVE_PATH
jev-filter read ARCHIVE_PATH --id 'code.py:retry_timeouts:4'
```

Then use native source review, call-site inspection and relevant tests to verify the
behavior you intend to change. Revision guards reject sources changed during
selection; they do not prove correctness or authorize editing. Keep source IDs in
the agent's reasoning so later claims can be checked against the file.

Before adopting this on a real workload, compare recall, false positives, reviews,
whole-operation time, returned context and actual model usage. The
[published benchmarks](benchmarks.md) include negative latency and cost cases;
semantic filtering does not promise every code task will become faster or cheaper.
See [RAG result filtering](search-result-filtering.md) and
[log triage](log-triage.md) for the same evidence pattern in other inputs.
