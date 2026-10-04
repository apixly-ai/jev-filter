<p><img src="assets/hero.svg" alt="Jev Filter: give your agent the signal. Collect once, decide with context, return the proof."></p>

# Give your agent the signal.

**91.6–97.2% less returned tool context.** Paid A/B on 2026-10-04: 24 real agent runs, three synthetic scenarios, two primary models and two repetitions per arm. Give your agent the relevant evidence; keep every original recoverable by ID.

<p class="home-actions"><a class="primary" href="getting-started.md">Get started →</a><a href="agent-quickstart.md">Connect your agent</a><a href="benchmarks.md">Inspect the evidence</a></p>

## Put more reasoning behind less noise

**91.6–97.2% less returned tool context**, measured in **24 real agent runs** on 2026-10-04: three synthetic scenarios, two primary models and two repetitions per arm. The filtered agent completed **12/12** operations; raw context completed **11/12**. All **24/24** returned the exact expected ID sets.

| Attention for the hard part | Evidence you can recover | Interfaces you can trust |
|---|---|---|
| Collect and judge inside one program operation. The primary agent receives the selected evidence and unresolved IDs. | Keep originals by source ID, typed judgments and decision receipts. Source freshness and final checks remain independent. | **13/13 paid E2E checks passed** on Python CLI, freshly installed published npm JS/native, official MCP, local extraction and survey. |

**Find more relevant code.** Native filtering after opt-in recall recovered **10/12** matches, versus **4/12** with exact candidates, with no false positives. **Inspect the right changes.** Bounded diff triage found all four target changes in both repetitions while returning **23.9% less context** than retaining every file. [Live source data and the added work](benchmarks.md).

**Batch the repeated judgments.** Fresh 96-record tests used **56.5% fewer Jev input tokens** and made batch-parallel filtering **61.2% faster** than single-record parallel. All **12/12** runs were exact. This measures the Jev operation, not whole-agent speed. [Stage data](../benchmarks/results/2026-10-04-live-batching.json).

The same core fits **CLI, Python, JavaScript / TypeScript and read-only MCP**, plus a portable agent skill. Automatic batching, at most 30 concurrent requests and no inference-result cache keep the repeated work in the program. [Connect your agent](agent-quickstart.md#javascript-and-mcp).

## Show the gains. Keep the trade-offs.

**Context reduction is the strongest whole-agent result.** Five of six measured cells were slower by **0.1–18.4%**; cold API-equivalent cost ranged from **23.2% lower to 1.1% higher**. Codex subscription billing is unknown. These small synthetic samples do not guarantee speed or savings.

**Verified browser progress:** observed scroll-container evidence changed the nested-scroll fixture from **0/3 to 3/3** completed runs under the same strict **0.55 / 0.10** policy. Six ordinary goal runs still require review. A model's `DONE` is usable only when an independent final check agrees. [Current browser evidence, failed variants and recovery research](benchmarks.md).

[All measurements](benchmarks.md) · [Install and run](getting-started.md) · [Recorded synthetic workflows](showcase.md)

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
