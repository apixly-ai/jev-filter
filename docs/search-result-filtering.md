# Filter RAG search results into typed, traceable evidence

[简体中文](search-result-filtering.zh-CN.md)

Jev Filter can screen passages **after retrieval and before a main model reads
them**. Give it stable source IDs, the task's context and separate inclusion
conditions. It returns selected IDs, review IDs and compact evidence while retaining
the supplied originals locally. It does not crawl a corpus or replace a retriever.

This tutorial asks: **Which retrieved API passages support retrying HTTP 429 while
preventing duplicate charges?** The input is five fixed synthetic passages, not live
API documentation. The expected decisions below are handwritten teaching labels,
not a new accuracy or performance measurement.

## Where does filtering fit in RAG?

A typical workflow is:

```text
retriever → program checks → Jev typed decisions → evidence packet → main model
                                                               ↓
                                                   original-source verification
```

Keep keyword, vector or hybrid retrieval in your existing search system. Elastic's
[RAG overview](https://www.elastic.co/docs/solutions/search/rag) describes these
retrieval options; its [semantic reranking guide](https://www.elastic.co/docs/solutions/search/ranking/semantic-reranking)
describes reordering a retrieved shortlist by similarity to a query.

Reranking is useful when the problem is ordering relevance. This example asks for
multiple conditions: a passage must permit this retry **and** explain duplicate
protection. A highly relevant passage that omits the second condition remains
incomplete evidence. Jev's atomic contract produces separate
SUPPORTED / CONTRADICTED / UNKNOWN judgments; program rules then retain matches,
exclude known mismatches and preserve unresolved items for review. Filtering and
reranking can coexist, but their outputs answer different questions.

## Install and get the fixed inputs

The npm CLI requires Node.js 22+ on macOS or Linux. Windows can use WSL or the
[Python source install](getting-started.md#python-library-source-install).

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
git clone https://github.com/apixly-ai/jev-filter.git
cd jev-filter
```

`doctor` is offline. The semantic call later requires your own Typesafe API key and
is billable. Configure it using the [key guide](getting-started.md#configure-your-key);
never put a credential in a fixture or prompt.

The repo owns both [retrieved.json](../examples/search-filtering/retrieved.json) and
[analysis.json](../examples/search-filtering/analysis.json). Each record has `id`,
`text` and observed source metadata. The fixture's `synthetic://` references identify
local teaching sources; they are not real web URLs.

## Collect with code, decide with Jev

In a real integration, your program retrieves a bounded set, applies access and
exact metadata rules, deduplicates stable IDs and emits JSON. Check version or tenant
IDs with code when those fields already settle the question. Give each passage
enough surrounding content to assess the conditions; cutting away an exception can
change the answer.

The shared contract sets the goal, API version, exclusions and required context.
It also requires `source.api_version`, `source.source_uri` and `source.revision` on
each normalized record. Put metadata at the input record's top level: the CLI adds
the `source` wrapper. The two independent requirements are:

1. The passage explicitly permits an HTTP 429 retry for API v4.
2. The passage states how the retry avoids a duplicate charge.

Inspect admission and batching without inference:

```sh
jev-filter query --input examples/search-filtering/retrieved.json \
  --analysis examples/search-filtering/analysis.json \
  --task 'Find API v4 passages permitting HTTP 429 retries with duplicate-charge protection' \
  --plan
```

The version-missing record is deferred for missing context. Planning does not make
semantic judgments. When you choose to run billable inference, remove `--plan`:

```sh
jev-filter query --input examples/search-filtering/retrieved.json \
  --analysis examples/search-filtering/analysis.json \
  --task 'Find API v4 passages permitting HTTP 429 retries with duplicate-charge protection' \
  > search-result.json
```

| Source ID | Expected disposition | Reason |
|---|---|---|
| `v4-429-idempotency` | Match | Both conditions are explicit |
| `v4-timeout` | Exclude | Describes a different failure phase |
| `v4-429-no-retry` | Exclude | Explicitly forbids this retry |
| `v4-429-incomplete` | Review | Duplicate protection is unknown |
| `version-missing` | Review | Required version metadata is absent |

## Consume evidence and verify the original

Parse `selected_ids`, `review_ids` and `complete` together. This fixture includes
expected reviews, so a semantic run may exit **2** with a useful partial JSON packet.
Do not discard stdout because the process returned a nonzero status. Exit 0 means
completed processing; it does not prove the statements true. Exit 1 means an input,
setup or execution error. See the [CLI contract](cli.md).

Pass the compact packet to the main model. Recover a supplied original by copying
the returned `archive` path:

```sh
jev-filter list ARCHIVE_PATH
jev-filter read ARCHIVE_PATH --id v4-429-idempotency
```

Your application must independently verify the authoritative source, version,
permissions and freshness before using a passage as a policy claim. The archive
preserves what the collector supplied; it cannot establish that a source was honest
or current. Missing shared context returns `NEEDS_CONTEXT`; missing per-record facts
remain reviewable. Keep both in the workflow.

## When is this worth adding?

Use it when many retrieved passages require the same semantic conditions. Use
native filtering for exact fields and let the main model handle a few short passages
or open reasoning. Measure retrieval recall, selection quality, review/failure rate,
returned context, whole-operation time and both models' usage before changing your
production pipeline. The [published benchmarks](benchmarks.md) include reduced
returned context **and** slower whole operations and higher-cost cases; they are
fixed synthetic tests, not a universal speed or cost promise.

Continue with [semantic code search](semantic-code-search.md),
[correlated log triage](log-triage.md) or the
[context contract](context-contract.md).
