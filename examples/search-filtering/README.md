# Fixed tutorial inputs

These small synthetic fixtures demonstrate contracts, source recovery and review.
They contain no real service policy, customer logs or credentials. `synthetic://`
references identify fixture passages; they are not external documentation.

- `retrieved.json` + `analysis.json`: multiple conditions over retrieved passages.
- `code.py` + `code-analysis.json`: complete functions, including lexical distractors.
- `events.jsonl` + `log-analysis.json`: current versus recovered request histories.

Handwritten expected semantic dispositions, **not measured inference results**:

| Fixture | Match | Exclude | Review |
|---|---|---|---|
| Retrieved passages | `v4-429-idempotency` | `v4-timeout`, `v4-429-no-retry` | `v4-429-incomplete`, `version-missing` |
| Code symbols | `retry_timeouts` | `report_timeout`, `run_once` | Any source/parse failure |
| Request histories | `correlated:current-tls` | `correlated:recovered`, `correlated:current-http` | `correlated:unknown-phase` |

From a source checkout installed in a virtual environment with `.[code,dev]`, run:

```sh
python examples/search-filtering/verify.py
```

This validates contracts, collects fixed code/log candidates and plans admission
without network inference. It does not test semantic accuracy, latency or cost.
The tutorial pages explain the opt-in, billable CLI calls:
[search filtering](../../docs/search-result-filtering.md),
[code search](../../docs/semantic-code-search.md),
[log triage](../../docs/log-triage.md).
