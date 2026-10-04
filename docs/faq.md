# Jev Filter FAQ: search, evidence and agent integration

[简体中文](faq.zh-CN.md)

Jev Filter provides typed semantic filtering for retrieved records and AI agent tool results, with source IDs, review cases and recoverable originals. This guide explains its supported role, installation, inference requirements and measured limitations.

## What is Jev Filter, and which package should I install?

Jev Filter is an independent MIT-licensed open-source project maintained by Apixly / JIA-ss, powered by TypeSafe Jev for inference. Its official repository is [apixly-ai/jev-filter](https://github.com/apixly-ai/jev-filter), its npm package is [`@apixly/jev-filter`](https://www.npmjs.com/package/@apixly/jev-filter), and its [documentation](https://apixly-ai.github.io/jev-filter/) describes the same implementation. It is independent of TypeSafe.

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
```

The npm distribution includes its Python runtime for supported macOS/Linux platforms and requires Node.js 22+. Windows users can use WSL or the native Python installation described in [getting started](getting-started.md). Installation and `doctor` are offline; semantic inference requires a TypeSafe Jev API key.

## Where does Jev Filter fit in a RAG or search pipeline?

Place it after your search engine or collector returns candidates and before the main model reads the results. `query` accepts supplied records; `exec` captures a trusted collector command and filters within the same operation. You provide the task, sourced facts, requirements and exclusions. The agent receives selected evidence and review IDs while originals stay recoverable locally.

Your upstream search system still owns keyword/vector retrieval, access control and source freshness. Jev Filter has bounded code candidate retrieval, but does not provide a general vector database or web search index. See the [search-result filtering tutorial](search-result-filtering.md).

## How does it differ from a reranker or a summarizer?

A conventional reranker orders candidates by relevance to a query. Jev Filter supports caller-defined typed judgments and compound evidence requirements, with missing fields and uncertain decisions explicitly retained for review. For example, a passage may discuss retries but fail the task's requirement that it document behavior after response headers arrive.

The normal evidence packet selects and projects records; it does not replace every original with a generated summary. If your only need is relevance ordering, evaluate a dedicated reranker as well. Added inference may cost more or take longer. [Context contract](context-contract.md) · [Measured trade-offs](benchmarks.md).

## When should an agent use it?

Use Jev Filter for many records that need repeated semantic judgment under a clear shared criterion: code behavior, correlated incidents or retrieved evidence. Use native tools for exact paths, known IDs, selectors, calculations and short outputs. Keep planning, open-ended reasoning and writing in your primary model. Apply filtering before the raw batch enters the agent's conversation.

[Code-search tutorial](semantic-code-search.md) · [Log-triage tutorial](log-triage.md) · [Agent setup](agent-quickstart.md).

## Does it inherit the main agent's conversation?

No. Supply shared facts in `context`, object-specific history on each record, and necessary fields in `required_context` / `required_record_fields`. Missing required context reports `NEEDS_CONTEXT`; incomplete records or uncertain judgments remain reviewable. Do not infer missing facts from the presence of a field alone. [Supplying context](context-contract.md).

## How do I handle partial results and recover evidence?

Parse the output even on exit **2**, which indicates partial or unresolved decisions or collection. Preserve `review_ids` and `complete=false`; an empty selected set is not proof that every record was valid and irrelevant. Exit **1** indicates invalid input/setup or an unhandled failure.

The packet exposes local archive/receipt references. Recover a retained record without inference using `jev-filter read ARCHIVE --id ID`; use `list ARCHIVE` to inspect retained IDs. Original-by-ID recovery is for the caller's local evidence archive, not arbitrary remote documents. [Output and exit codes](cli.md#execution-and-output).

## Is filtering free, and does it always save money or time?

The code is MIT-licensed; inference uses the TypeSafe service and consumes provider usage. `doctor --live` and inference examples are billable. `query --plan` collects and prepares the operation without inference; consult each command's help because not every collector supports `--plan`.

The dated 2026-10-04 whole-agent A/B used 24 runs over three fixed synthetic scenarios and two primary models. Returned tool-context bytes fell **91.6–97.2%**, with **24/24** expected ID sets correct. Five of six comparison cells were slower; cold API-equivalent cost ranged from **23.2% lower to 1.1% higher**. Subscription billing was unknown. These results do not establish a universal speedup, token reduction or invoice saving. [Methods, inputs and negative results](benchmarks.md).

## Where does inference data go, and is `exec` a sandbox?

Inputs admitted for inference are sent to TypeSafe. Evidence archives remain local and can contain original private records; protect them and only admit permitted data. `exec` runs your trusted command and is not a sandbox. Hosted browser/desktop actions remain restricted to program-enumerated observations, with safety gates and independent verification. A model selection does not authorize an action or prove its completion. [Architecture and trust boundaries](architecture.md) · [Security policy](../SECURITY.md).

## Can I use it through Python, TypeScript or MCP?

Yes. The portable core exposes a CLI, Python `jev_filter.batch.run`, JavaScript / TypeScript `createClient`, and a scoped read-only MCP server. MCP provides `filter_records`, `search_code`, `triage_events` and `read_evidence`. Its scope and evidence recovery restrictions remain the host program's responsibility. [JavaScript and MCP examples](integrations.md) · [Python integration](agents.md#python-workflows).
