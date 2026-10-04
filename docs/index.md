<p><img src="assets/hero.svg" alt="Jev Filter: give your agent the signal. Collect once, decide with context, return the proof."></p>

# Give your agent the signal.

**Turn large tool outputs into decisions with evidence.** Jev Filter collects inside the program, applies typed semantic judgment using your task and context, and returns the relevant records plus unresolved IDs. Your agent keeps its attention for planning, reasoning and the cases that need it.

<p class="home-actions"><a class="primary" href="getting-started.md">Get started →</a><a href="agent-quickstart.md">Connect your agent</a><a href="benchmarks.md">Inspect the evidence</a></p>

## Three reasons to build with Jev Filter

| Focused context | Traceable decisions | Verified execution |
|---|---|---|
| The 2026-09-23 whole-operation benchmark returned **88–97% less tool context**, across 48 synthetic agent runs. | Source IDs, retained local originals and decision receipts. Unknowns and partial failures remain visible. | For hosted browser/desktop goals, Jev selects observed controls while the program owns execution and final-state checks. |

The same core connects through **CLI, Python, JavaScript / TypeScript and read-only MCP**, with a portable skill for your agent. Automatic batching reduces repeated input, concurrency stays at or below 30, and inference results are never cached. [Performance and cost trade-offs](benchmarks.md) belong to their dated experiments; they are not guarantees for your workload.

## A stronger core in 0.4

Configure per-question uncertainty policies, collect code candidates and Git diffs,
and evaluate saved judgments before changing automation. JavaScript and read-only MCP
adapters connect these capabilities to existing agents without duplicating inference.
[Integration examples](agent-quickstart.md#javascript-and-mcp).

The current offline decision A/B meets **13/13 expected behaviors**, versus **3/13**
on the pinned baseline, with **3 → 0 false fixture actions**. These are scripted
behavior checks, not model accuracy. Reviews and returned diagnostic context increase.
[Published result](../benchmarks/results/2026-10-04-decisions.json) ·
[All measurements and limitations](benchmarks.md).

## Start with your task

| Your goal | Your next step |
|---|---|
| Install and see a selected record | [Get started](getting-started.md) |
| Make a coding agent use Jev Filter | [Five-minute agent quickstart](agent-quickstart.md) |
| Capture tool output, find code or triage logs | [Copyable task recipes](recipes.md) |
| Use browser, desktop or survey execution | [Hosted execution](hosted-execution.md) · [Recorded runs](showcase.md) |
| Define context, judgment and review policies | [Context contract](context-contract.md) |
| Embed inference in an existing program | [Integration guide](agents.md) |
| Connect JavaScript/MCP or evaluate saved judgments | [Adapters and evaluation](integrations.md) |
| Check quality, latency, usage and costs | [Benchmarks and source data](benchmarks.md) |

## Reference and project

[CLI reference](cli.md) · [Architecture](architecture.md) · [Local usage dashboard](statistics.md) · [Distribution](distribution.md) · [Development and releases](development.md) · [README design](readme-design.md)

Inference inputs are sent to TypeSafe. `exec` runs your trusted command; hosted execution is restricted to program-enumerated actions. Keep identity, authorization, freshness and verification in your own workflow. [Trust boundaries](architecture.md).

Jev Filter is an independent MIT project maintained by Apixly / JIA-ss. [GitHub repository](https://github.com/apixly-ai/jev-filter) · [简体中文](index.zh-CN.md)
