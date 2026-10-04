# One decision core across your agent stack

[简体中文](integrations.zh-CN.md)

Use the native CLI, the Python API, the typed JavaScript client or read-only MCP.
Each retains selected IDs, unresolved IDs, private evidence receipts and honest usage.
The core owns collection and judgment; your business executor keeps identity,
authorization, idempotency and outcome verification.

## JavaScript and TypeScript

```sh
npm install @apixly/jev-filter
```

```js
import { createClient } from '@apixly/jev-filter';

const client = createClient({ timeoutMs: 120_000 });
const abortController = new AbortController();
const records = [
  { id: 'a', text: 'fixture-r17: DNS recovered; the current request succeeds.' },
  { id: 'b', text: 'fixture-r17: the current request still fails DNS lookup before any HTTP response.' },
];
const { packet, exitCode } = await client.query(records, {
  task: 'Find CURRENT connection failures before an HTTP response.',
  analysis: {
    required_context: ['deployment'],
    context: { deployment: 'fixture-r17' },
    uncertainty: { min_top_probability: 0.7, min_margin: 0.15 },
  },
  signal: abortController.signal,
});
// Parse exit 2 too: packet.review_ids holds evidence that needs another look.
```

`codeSearch`, `triage` and `diffReview` expose the corresponding fixed CLI entrypoints.
There is no arbitrary `exec` method. Arguments travel as literal argv with `shell:false`;
analysis files are temporary and private. Output has a byte budget, timeouts/cancellation
terminate the child, and an unsuccessful process never returns its raw stderr.

The default client uses the installed native distribution. Python-first applications can
configure a trusted executable with `createClient({command:['jev-filter']})`. The executable
is application configuration, never model-generated data. Cancellation may leave provider
usage unknown; do not assign a zero bill to an interrupted call.

## Read-only MCP

```json
{
  "mcpServers": {
    "jev-filter": {
      "command": "jev-filter",
      "args": ["mcp", "--root", "/path/to/your/workspace"]
    }
  }
}
```

Provide the TypeSafe test or application credential through the host's environment or
credential file configuration. Never put a key in the command arguments or committed JSON.

| Tool | Input and scope |
|---|---|
| `filter_records` | Supplied records, task and optional analysis contract |
| `search_code` | Regex plus optional query/caller expansion, inside the configured root |
| `triage_events` | Supplied events, correlated and redacted inside the program |
| `read_evidence` | One bounded record from an unchanged archive created in this server session |

MCP exposes no shell, browser mutation, arbitrary file reader or external messaging tool.
Symlinks cannot escape the workspace boundary. Evidence retrieval checks the archive hash;
it does not reuse an inference result. Stdio serves requests serially; disconnect/terminate
the process to end a run. In-flight network cancellation is not guaranteed.

This adapter implements the connection-scoped MCP revisions from 2024-11-05 through
2025-11-25 and negotiates one of those versions. It does not claim the newer stateless
2026-07-28 profile. An independent official MCP client is used for the release E2E check.

## Version your decision

```json
{
  "contract": {"id":"incident.connection", "version":"1"},
  "requirements": [
    {"id":"current", "statement":"The CURRENT request failed before any HTTP headers.", "expected":true}
  ],
  "uncertainty": {
    "min_top_probability":0.7,
    "min_margin":0.15,
    "questions":{"current":{"min_confidence":0.4}}
  }
}
```

The result records a semantic fingerprint tied to the rule/model. Supplying an expected
fingerprint detects a mismatched contract. This supports audit and evaluation; an old
receipt never becomes permission to act. Confidence summarizes a probability distribution,
not measured task accuracy. Validate thresholds against your domain's independent labels.

Filtering uncertainty is opt-in for compatibility. Hosted browser/desktop defaults require
a top probability of 0.55 and a top-two margin of 0.10 before a selected operation, target or
value executes. `needs_review` returns the failed metric and evidence for the planning agent.
Use `--uncertainty FILE` for per-question policy; zero thresholds reproduce legacy behavior.

## Evaluate saved judgments offline

From a repository checkout, run the public synthetic example without a model call:

```sh
jev-filter eval --input examples/evaluation.json --output local-results/evaluation.json
```

Replace the input with your labeled saved probabilities from separate calibration and
holdout groups. The evaluator selects a threshold on
calibration data only, then reports holdout accuracy/coverage, false positives/negatives,
review/failure counts, Brier score and reliability bins. It makes no model calls and does
not fit a probability calibrator. Mixed model/contract records and split leakage are refused.

See [the example dataset](../examples/evaluation.json), [CLI](cli.md) and
[release benchmarks](benchmarks.md) for reproducible commands and limits.
The demonstration uses manually defined probabilities and labels; its result shows
the interface and review behavior, not a model's accuracy.

## Compare another model

From a repository checkout; these benchmarks are development tooling:

```sh
pip install '.[code,dev,bench-llm]'
python -m benchmarks.providers --provider jev --model jev-1.13.0 --output plan.json
# Explicit opt-in, billable; use a new output file and supplied test credentials:
python -m benchmarks.providers --live --provider openai --model YOUR_TEST_MODEL --output llm.json
```

The optional benchmark uses TypeSafe's official System One Adapter and the same synthetic
state/questions as Jev. It reports retry-total usage, failures and unknowns, suppresses raw
provider debug traces and distinguishes generated LLM probabilities from native Jev output.
Providers need their respective SDK extras and explicit credentials. This comparison covers
the filtering operation; it excludes a primary agent continuation and is not an automatic
production fallback.
