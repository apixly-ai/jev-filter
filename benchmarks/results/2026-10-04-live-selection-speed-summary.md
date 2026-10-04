# 96 records. A complete selection in 1.31 seconds.

On 2026-10-04, Jev Filter returned the exact 48 matching IDs from 96 synthetic
records in a **median 1.313 seconds**. Direct screening through the signed-in
Codex CLI returned the same complete ID set in **13.421 seconds with
gpt-5.6-luna** and **14.543 seconds with gpt-6-astra**. Each path ran three times,
in rotating order. All nine runs were correct and complete; none needed review.

This measures the **screening step through the available execution paths**.
Jev used its native typed API; the primary models used the authenticated Codex
CLI with medium reasoning effort. The primary timing includes process startup
and the agent/provider turn. It is not an isolated native-model or direct-API
comparison, and no primary continuation followed Jev. It does not establish a
10× whole-agent speedup.

| Path | Median screening time | Range | Exact and complete |
| --- | ---: | ---: | ---: |
| Jev Filter · jev-1.13.0 | 1.313 s | 1.238–1.375 s | 3/3 |
| Codex CLI · gpt-5.6-luna | 13.421 s | 13.210–13.932 s | 3/3 |
| Codex CLI · gpt-6-astra | 14.543 s | 14.333–15.593 s | 3/3 |

## Same evidence, same required output

The candidate list is the redistributable 96-record fixture in
[`../fixture.py`](../fixture.py): current DNS/TCP/TLS establishment failures,
recovered historical failures, empty response bodies, and HTTP 503 responses.
The 96 rows repeat eight simple bilingual templates twelve times; this is a
small screening smoke fixture, not broad task diversity. Both paths receive all
records and the same two atomic requirements:

1. The current request fails during DNS, TCP or TLS establishment, rather than
   a historical attempt.
2. The current request has not received HTTP response headers.

Both must return every matching observed ID, once each, with
`needs_review=false` only when the evidence is sufficient. Expected IDs remain
with the benchmark verifier; they are never supplied to either model. A tool
call, invented or duplicate ID, malformed response, failed subprocess, review,
or incomplete set cannot count as a complete correct run.

The common fixture contains **12,351 UTF-8 bytes**. The Jev request envelopes
contain 93,226 bytes across two automatically formed batches: 98 and 94 atomic
questions. Both requests run concurrently; the requested worker ceiling is 12,
but the effective concurrency is **2**. Each primary model receives a
13,224-byte supplied prompt plus a 196-byte output schema. Hidden CLI/system
input is included in measured model tokens, rather than these supplied-byte
counts. The canonical final ID-set JSON is 375 bytes for every run.

Jev processes a larger request/token volume here because the typed question
schema is repeated. The speed result comes from this specialized screening
path; this benchmark does not demonstrate fewer input tokens.

## Quality and actual usage

Across nine completed runs: **0 false positives, 0 false negatives, 0 reviews,
0 malformed answers, 0 tool violations, 0 timeouts, and 0 unknown-usage attempts**.
No inference-result cache or benchmark retry is used.

| Path · three runs | Input tokens | Cached input tokens | Output tokens |
| --- | ---: | ---: | ---: |
| Jev · 6 native API requests | 91,086 | Not exposed | 27,546 |
| gpt-5.6-luna · 3 completed turns | 59,052 | 0 | 788 |
| gpt-6-astra · 3 completed turns | 66,216 | 0 | 492 |

Jev's reported usage corresponds to an **estimated $0.003825612** at the dated
$0.042 per million input tokens and zero output-token rate in the
[TypeSafe model documentation](https://docs.typesafe.ai/models). Actual invoice
amounts are unavailable. Primary calls use Codex subscription authentication;
their usage is measured, but this report assigns no direct API invoice cost.
Provider prompt caching is distinct from an inference-result cache.

The per-request HTTP round-trip field was available but not captured by the
original harness; its nulls remain missing measurements. The transport-pool
elapsed time and complete screening wall clock were measured. Pure provider
inference latency and independent CLI process overhead are unavailable.

## Reproduce

Install this repository in a virtual environment with `.[code,dev]`, provide an
explicitly authorized synthetic-test TypeSafe key file and a signed-in Codex CLI,
then run:

```sh
TYPESAFE_API_KEY_FILE=/secure/path/test-key \
  python -m benchmarks.selection_speed --live \
  --records 96 --repeats 3 --workers 12 \
  --models gpt-5.6-luna gpt-6-astra \
  --output /tmp/selection-speed-new.json \
  --private-dir /tmp/selection-speed-private-new
```

Use fresh paths: the runner preserves prior results and keeps raw Codex traces
outside the repository. It uses no browser, customer data, or private maintainer
workflow. Three repetitions are a smoke sample; request conditions and provider
load may change the result. Read the
[recorded timings, outputs, fixture and source hashes](2026-10-04-live-selection-speed.json)
and the [incremental usage receipt](2026-10-04-live-selection-speed-usage.json).
The receipt does not rewrite the earlier cumulative usage series.

The measured runtime files match the reviewed 0.4.1 base commit
`69e319987465cf28134e22cef70d409dcea4b280`. The artifact records both the original
harness hash and the subsequently published harness hash. Follow-up harness
repairs improve optional request-latency capture and unexpected-failure reporting;
they do not alter the recorded decisions or screening wall clocks.

中文解读：同一批 96 条合成记录、同样的完整筛选输出，Jev 工具路径的中位响应为
**1.31 秒**，两条已登录 Codex CLI 路径为 **13.42 秒 / 14.54 秒**，三组各测三次，
9/9 完整正确。这说明明确语义条件下的批量筛选可以更快地返回结果；样本只涵盖此
筛选阶段，不能据此宣称原生模型推理或整轮 agent 快十倍。Jev 的本次输入字节和
token 更多，且主模型的订阅账单未知；这些限制应与速度结果一起呈现。
