# Agent quickstart

[简体中文](agent-quickstart.zh-CN.md)

[Full integration reference](agents.md)

**One tool call in; a compact evidence packet out.** Your agent supplies the task
and context. Jev Filter collects and judges internally. The agent handles planning,
open reasoning and unresolved evidence.

## 1. Install once

```sh
npm install -g @apixly/jev-filter
jev-filter doctor
```

Provide `TYPESAFE_API_KEY` or `TYPESAFE_API_KEY_FILE` in the agent tool environment.
Do not paste credentials into the prompt. Copy the supplied skill:

```sh
mkdir -p ~/.codex/skills
cp -R "$(npm root -g)/@apixly/jev-filter/skills/jev-filter" ~/.codex/skills/
```

For Claude Code, use `~/.claude/skills/`. Review existing local customizations before
replacing a skill. Installation does not automatically edit global instructions.

## 2. Make the routing choice

| Task | Route |
|---|---|
| Exact path, ID, field, selector or calculation | Native tool / deterministic code |
| Many records, clear repeated semantic judgment | Jev Filter |
| Planning, writing or open-ended reasoning | Primary model |
| Existing workflow already uses Jev | Call it directly; do not add another filter |

## 3. Pass a small context contract

Save as `analysis.json`:

```json
{
  "mode": "choose",
  "context": {"project": "Beta", "format": "JSON"},
  "required_context": ["project", "format"],
  "required_record_fields": ["source.project", "source.format"]
}
```

Then execute a complete, reproducible call:

```sh
jev-filter query --input - --analysis analysis.json \
  --task 'Choose the export matching the project and format in context' <<'JSON'
[
  {"id":"a","text":"Export records","project":"Alpha","format":"JSON"},
  {"id":"b","text":"Export records","project":"Beta","format":"JSON"},
  {"id":"c","text":"Export records","project":"Beta","format":"CSV"}
]
JSON
```

Expected: `selected_ids=["b"]`, `review_ids=[]`, `complete=true`. To use your real
collector, replace `query --input -` with `exec ... -- YOUR_COMMAND ARGS`; see the
[command recipe](recipes.md#1-custom-command-output). Keep raw collection inside
that call; do not dump it into the conversation first.

## 4. Consume, review, recover

- Use complete typed decisions for the stated predicate without repeating them.
- `review_ids` or `complete=false`: inspect only the necessary originals.
- Exit **2** still carries a parseable result; do not throw the packet away.
- Retrieve evidence with `jev-filter read ARCHIVE_PATH --id SOURCE_ID`.
- Keep permission, identity, freshness and execution verification in the host workflow.

Jev does not inherit your chat history. Supply relevant sourced facts and per-record
history; missing facts must remain unresolved. Automatic batching and up to 30 requests
are enabled; no result cache is used. [Context details](context-contract.md).

The legacy `jev-context` command and `jev_context` Python imports remain compatible.
For new Python integrations, use `from jev_filter.batch import run`.

## JavaScript and MCP

The npm package also exports a typed Node.js client. Install it in your project with
`npm install @apixly/jev-filter`, then call the same CLI core:

```js
import { createClient } from '@apixly/jev-filter';

const client = createClient({ timeoutMs: 120_000 });
const { packet, exitCode } = await client.query([
  { id: 'a', text: 'DNS recovered; requests now succeed.' },
  { id: 'b', text: 'DNS lookup still fails before connection.' },
], {
  task: 'Find current unresolved DNS failures',
  analysis: {
    requirements: [
      { id: 'unresolved', statement: 'DNS currently fails and has not recovered.', expected: true },
    ],
  },
});

console.log(packet.selected_ids, packet.review_ids, exitCode);
// Exit 2 returns a usable packet with partial/review results.
```

`query`, `codeSearch`, `triage` and `diffReview` support an `AbortSignal` and bounded
output; the client has a configurable timeout. Handle cancellation as an uncertain
in-flight operation, not as permission to rerun a collector. The client does not
implement a second provider transport.

For an MCP-capable host, start a read-only server with a fixed workspace:

```sh
jev-filter mcp --root /path/to/workspace
```

A typical host configuration is:

```json
{
  "mcpServers": {
    "jev-filter": {
      "command": "jev-filter",
      "args": ["mcp", "--root", "/path/to/workspace"]
    }
  }
}
```

Configure credentials in the host's process environment, using its secret mechanism.
The server exposes only `filter_records`, `search_code`, `triage_events` and
`read_evidence`. Code collection is restricted to the workspace; evidence reading is
restricted to unchanged receipts created in that server session. It exposes no shell
execution, browser actions or arbitrary file reads. Inference remains billable and
still sends admitted input to TypeSafe. [Complete adapter contract](integrations.md) ·
[Command reference](cli.md).

## Improve a workflow with measured evidence

Use opt-in retrieval when a code task needs more than an exact lexical match:

```sh
jev-filter code-search 'quota|billing' --root . \
  --query 'deduct balance after a completed request' --expand-callers \
  --max-files 100 --task 'Find implementations that deduct the user balance'

jev-filter diff-review --root . --base main \
  --task 'Find changes that weaken authorization checks'
```

These collectors return review candidates and scope receipts. A broader candidate
pool may increase recall, irrelevant results and returned context. Semantic diff
judgments guide inspection; they do not replace compilation, tests or review.

Evaluate saved labeled decisions without a model call:

```sh
# From a repository checkout; use your own dataset for a real assessment.
jev-filter eval --input examples/evaluation.json --threshold 0.5 --threshold 0.8
```

Prepare the input using the [evaluation guide](integrations.md#evaluate-saved-judgments-offline).
Keep groups separated between
calibration and test sets, inspect failures and review coverage, and measure the
whole operation before changing routing. The report diagnoses probabilities; it does
not fit or apply a calibrated probability model to production decisions.
